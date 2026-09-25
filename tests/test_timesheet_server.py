import json
import threading
import urllib.error
import urllib.request
from datetime import date

import pytest

from devflow.timesheet import DraftLine, ProjectRule, Rules, Sheet, Worklog, save_draft
from devflow.timesheet_server import App, make_server

WEEK = '2026-W38'
MON = date(2026, 9, 14)


def rules():
    return Rules({'client': Sheet('client', 'se', 'me', 8, 40)}, [ProjectRule('green', 'client', 'per-issue', 'SE')])


class Calls:
    def __init__(self):
        self.fetch = self.compute = 0

    def fetch_fn(self, rules, week):
        self.fetch += 1
        return {'client': [Worklog('client', 'SE-1', MON, 3600, 'ревью')]}

    def compute_fn(self, rules, logs, week):
        self.compute += 1
        return [DraftLine('client', MON, 'SE-2', 1800 * self.compute)]


@pytest.fixture
def served(tmp_path):
    calls = Calls()
    server = make_server(App(rules(), tmp_path, calls.fetch_fn, calls.compute_fn), 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, calls, tmp_path
    server.shutdown()
    server.server_close()


def call(server, path, method='GET', body=None):
    url = f'http://127.0.0.1:{server.server_address[1]}{path}'
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(url, data, method=method)) as r:
        return json.loads(r.read())


def restart(server, calls, state):
    server.shutdown()
    server.server_close()
    fresh = make_server(App(rules(), state, calls.fetch_fn, calls.compute_fn), 0)
    threading.Thread(target=fresh.serve_forever, daemon=True).start()
    return fresh


def test_listens_only_on_loopback(served):
    assert served[0].server_address[0] == '127.0.0.1'


def test_get_week_returns_summary_without_draft(served):
    server, calls, state = served
    save_draft(WEEK, [DraftLine('client', MON, 'SE-9', 900)], state)
    data = call(server, '/api/week/W38')
    assert data['week'] == WEEK
    assert data['sheets']['client']['total'] == 3600
    assert data['sheets']['client']['worklogs'][0]['key'] == 'SE-1'
    assert data['draft']['lines'][0]['key'] == 'SE-9'
    assert data['draft']['generated']
    call(server, f'/api/week/{WEEK}')
    assert (calls.fetch, calls.compute) == (1, 0)


def test_recompute_calls_draft_once_and_rewrites_file(served):
    server, calls, state = served
    save_draft(WEEK, [DraftLine('client', MON, 'SE-9', 900)], state)
    call(server, '/api/week/W38')
    data = call(server, '/api/week/W38/recompute', 'POST')
    assert calls.compute == 1 and calls.fetch == 2
    assert [line['key'] for line in data['draft']['lines']] == ['SE-2']
    assert json.loads((state / f'draft-{WEEK}.json').read_text())['lines'][0]['key'] == 'SE-2'


def test_index_inlines_design_tokens(served):
    url = f'http://127.0.0.1:{served[0].server_address[1]}/'
    html = urllib.request.urlopen(url).read().decode()
    assert '/*TOKENS*/' not in html and '--sig' in html and '__WEEK__' not in html


def test_line_edit_and_manual_entry_survive_restart(served):
    server, calls, state = served
    save_draft(WEEK, [DraftLine('client', MON, 'SE-9', 900), DraftLine('client', MON, 'SE-8', 900)], state)
    call(server, f'/api/week/{WEEK}/draft/0', 'PUT', {'seconds': 7200, 'comment': 'поиск', 'key': 'se-7'})
    call(server, f'/api/week/{WEEK}/draft/1', 'DELETE')
    data = call(server, f'/api/week/{WEEK}/manual', 'POST',
                {'sheet': 'client', 'day': '2026-09-15', 'key': 'SE-5', 'seconds': 3600, 'comment': 'созвон'})
    assert [ln['key'] for ln in data['draft']['lines']] == ['SE-7', 'SE-5']
    server = restart(server, calls, state)
    try:
        data = call(server, f'/api/week/{WEEK}')
        first = data['draft']['lines'][0]
        assert (first['key'], first['seconds'], first['comment'], first['edited']) == ('SE-7', 7200, 'поиск', True)
        assert data['manual'] == [{'sheet': 'client', 'day': '2026-09-15', 'key': 'SE-5', 'seconds': 3600,
                                   'comment': 'созвон'}]
        data = call(server, f'/api/week/{WEEK}/manual/0', 'DELETE')
        assert data['manual'] == [] and [ln['key'] for ln in data['draft']['lines']] == ['SE-7']
    finally:
        server.shutdown()
        server.server_close()


def test_recompute_keeps_edited_line_and_drops_removed(served):
    server, calls, state = served
    calls.compute_fn = lambda r, logs, week: [DraftLine('client', MON, 'SE-2', 1800), DraftLine('client', MON, 'SE-3', 900),
                                              DraftLine('client', MON, 'SE-4', 900)]
    server = restart(server, calls, state)
    try:
        call(server, f'/api/week/{WEEK}/recompute', 'POST')
        call(server, f'/api/week/{WEEK}/draft/0', 'PUT', {'seconds': 5400})
        call(server, f'/api/week/{WEEK}/draft/1', 'DELETE')
        data = call(server, f'/api/week/{WEEK}/recompute', 'POST')
        lines = {ln['key']: ln for ln in data['draft']['lines']}
        assert set(lines) == {'SE-2', 'SE-4'}
        assert lines['SE-2']['seconds'] == 5400 and lines['SE-2']['edited']
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize('body', [{'seconds': -1}, {'key': 'нет'}, {'day': '2026-09-30'}, {'sheet': 'x'}])
def test_bad_edit_is_rejected(served, body):
    server, _, state = served
    save_draft(WEEK, [DraftLine('client', MON, 'SE-9', 900)], state)
    with pytest.raises(urllib.error.HTTPError) as e:
        call(server, f'/api/week/{WEEK}/draft/0', 'PUT', body)
    assert e.value.code == 400
    assert json.loads((state / f'draft-{WEEK}.json').read_text())['lines'][0]['seconds'] == 900
