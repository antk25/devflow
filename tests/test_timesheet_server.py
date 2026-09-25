import json
import threading
import urllib.error
import urllib.request
from datetime import date

import pytest

from devflow.timesheet import (DraftLine, ProjectRule, Rules, Sheet, Worklog, comment_hints, remember_comments,
                               save_draft)
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


def test_unknown_path_is_404_not_crash(served):
    with pytest.raises(urllib.error.HTTPError) as e:
        call(served[0], '/favicon.ico')
    assert e.value.code == 404


def test_index_inlines_design_tokens(served):
    url = f'http://127.0.0.1:{served[0].server_address[1]}/'
    html = urllib.request.urlopen(url).read().decode()
    assert '/*TOKENS*/' not in html and '--sig' in html and '__WEEK__' not in html


def test_page_scripts_are_served_locally(served):
    base = f'http://127.0.0.1:{served[0].server_address[1]}'
    html = urllib.request.urlopen(base + '/').read().decode()
    assert '/app.mjs' in html and 'https://' not in html
    for path in ('/app.mjs', '/vendor/preact-htm.mjs'):
        with urllib.request.urlopen(base + path) as r:
            assert r.headers['Content-Type'].startswith('text/javascript') and r.read()
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + '/vendor/other.mjs')
    assert e.value.code == 404


def test_explicit_key_clears_mirror_flags_and_hours_clear_overflow(served):
    server, _, state = served
    save_draft(WEEK, [DraftLine('client', MON, '', 900, flags=['no-mirror', 'create-mirror'], mirror_of='SE-9'),
                      DraftLine('client', MON, 'SE-8', 900, flags=['overflow', 'no-mirror'])], state)
    call(server, f'/api/week/{WEEK}/draft/0', 'PUT', {'key': 'SE-7'})
    data = call(server, f'/api/week/{WEEK}/draft/1', 'PUT', {'seconds': 1800})
    first, second = data['draft']['lines']
    assert (first['key'], first['flags'], first['mirror_of']) == ('SE-7', [], 'SE-9')
    assert second['flags'] == ['no-mirror']


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


class FakeJira:
    def __init__(self):
        self.calls, self.next_id = [], 100

    def __call__(self, cmd, **kw):
        self.calls.append(cmd[1:])
        self.next_id += 1
        out = json.dumps({'id': str(self.next_id)}) if cmd[1] == 'add' else ''
        return type('P', (), {'returncode': 0, 'stdout': out, 'stderr': ''})()


@pytest.fixture
def writable(tmp_path):
    calls, jira = Calls(), FakeJira()
    server = make_server(App(rules(), tmp_path, calls.fetch_fn, calls.compute_fn, jira), 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    save_draft(WEEK, [DraftLine('client', MON, 'SE-2', 7200, 'код'),
                      DraftLine('client', MON, 'SE-3', 900, flags=['no-mirror'])], tmp_path)
    yield server, jira, tmp_path
    server.shutdown()
    server.server_close()


def status(server, path, method, body=None):
    try:
        call(server, path, method, body)
    except urllib.error.HTTPError as e:
        return e.code
    return 200


def test_plan_lists_actions_and_skips_per_sheet(writable):
    server, jira, _ = writable
    plan = call(server, f'/api/week/{WEEK}/plan')
    client = plan['sheets']['client']
    assert [a['key'] for a in client['actions']] == ['SE-2'] and client['total'] == 7200
    assert client['skipped'][0]['why'] == 'no-mirror'
    assert plan['hash'] and jira.calls == []


def test_apply_without_matching_hash_sends_nothing(writable):
    server, jira, state = writable
    assert status(server, f'/api/week/{WEEK}/apply', 'POST', {}) == 409
    assert status(server, f'/api/week/{WEEK}/apply', 'POST', {'hash': 'x'}) == 409
    plan = call(server, f'/api/week/{WEEK}/plan')
    save_draft(WEEK, [DraftLine('client', MON, 'SE-2', 3600, 'код')], state)
    assert status(server, f'/api/week/{WEEK}/apply', 'POST', {'hash': plan['hash']}) == 409
    assert jira.calls == [] and not (state / 'sent.jsonl').exists()


def test_apply_writes_once_and_repeat_press_makes_no_duplicates(writable):
    server, jira, state = writable
    plan = call(server, f'/api/week/{WEEK}/plan')
    data = call(server, f'/api/week/{WEEK}/apply', 'POST', {'hash': plan['hash']})
    assert data['results'] == [{'sheet': 'client', 'day': MON.isoformat(), 'key': 'SE-2', 'worklog_id': '101', 'error': ''}]
    assert jira.calls[0][:2] == ['add', 'SE-2'] and jira.calls[0][-1] == '--yes'
    assert status(server, f'/api/week/{WEEK}/apply', 'POST', {'hash': plan['hash']}) == 409
    again = call(server, f'/api/week/{WEEK}/plan')
    assert again['sheets']['client']['actions'] == []
    call(server, f'/api/week/{WEEK}/apply', 'POST', {'hash': again['hash']})
    assert len(jira.calls) == 1
    assert len((state / 'sent.jsonl').read_text().splitlines()) == 1


def test_sent_change_requires_confirm(writable):
    server, jira, _ = writable
    assert status(server, f'/api/week/{WEEK}/sent/55', 'PUT', {'key': 'SE-1', 'seconds': 1800}) == 400
    assert status(server, f'/api/week/{WEEK}/sent/55', 'DELETE', {'key': 'SE-1', 'confirm': 'yes'}) == 400
    assert jira.calls == []


def test_sent_update_and_delete_with_confirm_sync_journal(writable):
    server, jira, state = writable
    plan = call(server, f'/api/week/{WEEK}/plan')
    call(server, f'/api/week/{WEEK}/apply', 'POST', {'hash': plan['hash']})
    call(server, f'/api/week/{WEEK}/sent/101', 'PUT', {'key': 'SE-2', 'seconds': 5400, 'confirm': True})
    assert jira.calls[-1] == ['update', 'SE-2', '101', '--seconds', '5400', '--yes']
    assert json.loads((state / 'sent.jsonl').read_text())['seconds'] == 5400
    call(server, f'/api/week/{WEEK}/sent/101', 'DELETE', {'key': 'SE-2', 'confirm': True})
    assert jira.calls[-1] == ['delete', 'SE-2', '101', '--yes']
    assert (state / 'sent.jsonl').read_text() == ''


def test_comment_hints_remember_own_comments_by_issue_and_project(tmp_path):
    logs = {'employer': [Worklog('employer', 'CAP-483', MON, 1800, 'QA', '7'),
                         Worklog('employer', 'CAP-1', MON, 900, 'Meeting', '8'),
                         Worklog('employer', 'CAP-1', MON, 900, 'Meeting', '9'),
                         Worklog('employer', 'CAP-2', MON, 900, 'без id')]}
    remember_comments(logs, tmp_path)
    remember_comments(logs, tmp_path)
    hints = comment_hints(tmp_path)
    assert hints['CAP-1'] == ['Meeting']
    assert hints['CAP'] == ['Meeting', 'QA']
    assert 'CAP-2' not in hints


def test_week_returns_comment_hints(served):
    server, _, state = served
    remember_comments({'client': [Worklog('client', 'SE-188', MON, 900, 'Meeting', '1')]}, state)
    assert call(server, f'/api/week/{WEEK}')['hints']['SE-188'] == ['Meeting']
