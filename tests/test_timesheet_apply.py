import json
import subprocess
from datetime import date

from devflow.timesheet import DraftLine, Unavailable, Worklog, apply, load_sent, plan_apply

MON, TUE = date(2026, 9, 21), date(2026, 9, 22)
WEEK = '2026-W39'


def lines():
    return [DraftLine('client', MON, 'SE-1', 3600),
            DraftLine('client', TUE, 'SE-2', 1800, 'ревью'),
            DraftLine('employer', MON, '', 3600, flags=['no-mirror'], mirror_of='SE-1'),
            DraftLine('employer', MON, 'GS-5', 900, flags=['ambiguous-mirror']),
            DraftLine('employer', TUE, 'GS-6', 900, flags=['overflow']),
            DraftLine('employer', TUE, 'CAP-1', 1800)]


class FakeRun:
    def __init__(self):
        self.calls, self.n = [], 100

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        self.n += 1
        return subprocess.CompletedProcess(cmd, 0, json.dumps({'id': str(self.n)}), '')


def test_without_yes_nothing_is_called(tmp_path):
    run = FakeRun()
    actions, _ = plan_apply(lines(), [], {'client': [], 'employer': []})
    assert apply(actions, False, WEEK, tmp_path, run) == []
    assert run.calls == []
    assert not (tmp_path / 'sent.jsonl').exists()


def test_flagged_lines_skipped_with_reason():
    actions, skipped = plan_apply(lines(), [], {'client': [], 'employer': []})
    assert [(x.key, x.sheet) for x in actions] == [('SE-1', 'client'), ('SE-2', 'client'), ('CAP-1', 'employer')]
    assert sorted(why for _, why in skipped) == ['ambiguous-mirror', 'no-mirror', 'overflow']


def test_sheet_filter_and_unavailable_sheet():
    actions, skipped = plan_apply(lines(), [], {'client': [], 'employer': Unavailable('401')}, {'client'})
    assert {x.sheet for x in actions} == {'client'} and skipped == []
    actions, skipped = plan_apply(lines(), [], {'client': [], 'employer': Unavailable('401')})
    assert {x.sheet for x in actions} == {'client'}
    assert all('недоступен' in why for _, why in skipped)


def test_yes_writes_journal_and_repeat_is_noop(tmp_path):
    run = FakeRun()
    live = {'client': [], 'employer': []}
    actions, _ = plan_apply(lines(), [], live)
    res = apply(actions, True, WEEK, tmp_path, run)
    assert [r[1] for r in res] == ['101', '102', '103']
    assert all(c[-1] == '--yes' and c[0].endswith('integrations/jira-worklog.sh') for c in run.calls)
    assert run.calls[1][1:] == ['add', 'SE-2', '--day', '2026-09-22', '--seconds', '1800', '--comment', 'ревью', '--yes']
    sent = load_sent(tmp_path)
    assert [s['worklog_id'] for s in sent] == ['101', '102', '103']
    again, _ = plan_apply(lines(), sent, live)
    assert again == []


def test_live_match_without_journal_is_noop():
    live = {'client': [Worklog('client', 'SE-1', MON, 3600), Worklog('client', 'SE-2', TUE, 1800, 'ревью')],
            'employer': [Worklog('employer', 'CAP-1', TUE, 1800)]}
    actions, _ = plan_apply(lines(), [], live)
    assert actions == []


def test_live_match_consumed_once_and_differs_by_seconds():
    live = {'client': [Worklog('client', 'SE-1', MON, 3600), Worklog('client', 'SE-2', TUE, 900, 'ревью')],
            'employer': []}
    doubled = lines() + [DraftLine('client', MON, 'SE-1', 3600)]
    actions, _ = plan_apply(doubled, [], live)
    assert [(x.key, x.seconds) for x in actions if x.sheet == 'client'] == [('SE-2', 1800), ('SE-1', 3600)]


def test_failed_call_not_journaled(tmp_path):
    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, '', 'jira-worklog: Jira ответила 400:\nbad')
    actions, _ = plan_apply(lines()[:1], [], {'client': []})
    res = apply(actions, True, WEEK, tmp_path, run)
    assert res[0][2] == 'bad'
    assert load_sent(tmp_path) == []
