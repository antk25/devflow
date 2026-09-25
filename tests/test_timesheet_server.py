import json
import threading
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


def call(server, path, method='GET'):
    url = f'http://127.0.0.1:{server.server_address[1]}{path}'
    with urllib.request.urlopen(urllib.request.Request(url, method=method)) as r:
        return json.loads(r.read())


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
