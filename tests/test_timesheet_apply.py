import json
import subprocess
from datetime import date

import pytest

from devflow import timesheet as ts
from devflow.timesheet import (DraftLine, ProjectRule, Rules, Sheet, Unavailable, Worklog, apply, load_draft,
                               load_manual, load_sent, mark_sent, parse_day, plan_apply, save_draft, save_manual)

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


def test_journal_and_live_copy_of_one_worklog_consume_one_line():
    line = DraftLine('client', MON, 'SE-1', 3600, 'x')
    sent = [{'sheet': 'client', 'day': MON.isoformat(), 'key': 'SE-1', 'seconds': 3600, 'comment': 'x', 'worklog_id': '42'}]
    live = {'client': [Worklog('client', 'SE-1', MON, 3600, 'x', '42')]}
    actions, _ = plan_apply([line, DraftLine('client', MON, 'SE-1', 3600, 'x')], sent, live)
    assert len(actions) == 1


def test_sent_line_is_not_offered_again_after_its_worklog_was_edited(tmp_path):
    save_draft(WEEK, [DraftLine('client', MON, 'SE-1', 3600, 'x', 'manual')], tmp_path)
    save_manual(WEEK, [{'sheet': 'client', 'day': MON.isoformat(), 'key': 'SE-1', 'seconds': 3600, 'comment': 'x'}],
                tmp_path)
    lines = load_draft(WEEK, tmp_path)
    actions, _ = plan_apply(lines, [], {'client': []})
    mark_sent(WEEK, apply(actions, True, WEEK, tmp_path, FakeRun()), tmp_path)
    assert [x.sent_id for x in load_draft(WEEK, tmp_path)] == ['101']
    assert load_manual(WEEK, tmp_path)[0]['sent_id'] == '101'
    sent = [{**load_sent(tmp_path)[0], 'seconds': 1800}]
    live = {'client': [Worklog('client', 'SE-1', MON, 1800, 'x', '101')]}
    assert plan_apply(load_draft(WEEK, tmp_path), sent, live)[0] == []


def test_pick_keeps_only_selected_sheet_days_and_does_not_list_the_rest_as_skipped():
    actions, skipped = plan_apply(lines(), [], {'client': [], 'employer': []}, pick={('employer', TUE)})
    assert [(x.sheet, x.key) for x in actions] == [('employer', 'CAP-1')]
    assert [why for _, why in skipped] == ['overflow']
    full, _ = plan_apply(lines(), [], {'client': [], 'employer': []}, pick=None)
    assert len(full) == 3


def test_parse_day_takes_iso_or_weekday_inside_the_week():
    assert parse_day('вт', WEEK) == TUE and parse_day('2026-09-21', WEEK) == MON
    with pytest.raises(ValueError):
        parse_day('2026-09-28', WEEK)
    with pytest.raises(ValueError):
        parse_day('завтра', WEEK)


def two_sheets():
    return Rules({'client': Sheet('client', 'se', 'me', 8, 40), 'employer': Sheet('employer', 'gs', 'me', 8, 40)},
                 [ProjectRule('green', 'client', 'per-issue', 'SE')])


@pytest.fixture
def cli(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(ts, 'load_draft', lambda week: lines())
    monkeypatch.setattr(ts, 'load_sent', lambda: [])
    monkeypatch.setattr(ts, 'fetch_worklogs', lambda rules, week: {'client': [], 'employer': []})
    monkeypatch.setattr(ts, '_load', lambda args: (args.week, two_sheets()))
    monkeypatch.setattr(ts.subprocess, 'run', run)
    return run


def test_cli_day_narrows_dry_run_to_that_day(cli, capsys):
    assert ts.main(['apply', '--week', WEEK, '--sheet', 'employer', '--day', 'вт']) == 0
    out = capsys.readouterr().out
    assert 'DRY RUN' in out and 'CAP-1' in out and 'GS-6' in out
    assert 'SE-2' not in out and 'GS-5' not in out and 'SE-1' not in out
    assert cli.calls == []


def test_cli_day_without_sheet_covers_every_sheet_that_day(cli, capsys):
    assert ts.main(['apply', '--week', WEEK, '--day', '2026-09-21']) == 0
    out = capsys.readouterr().out
    assert 'SE-1' in out and 'GS-5' in out and 'SE-2' not in out and 'CAP-1' not in out


def test_cli_day_outside_week_is_refused(cli, capsys):
    assert ts.main(['apply', '--week', WEEK, '--day', '2026-09-28', '--yes']) == 2
    assert 'вне недели' in capsys.readouterr().err and cli.calls == []
