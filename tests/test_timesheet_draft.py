from datetime import date, datetime, timedelta
from pathlib import Path

from devflow.timesheet import MSK, Worklog, activity, draft_client, draft_employer, load_rules, round_quarters

EXAMPLE = Path(__file__).resolve().parents[1] / 'skills/timesheet/timesheet.example.json'
RULES = load_rules(EXAMPLE, {'productsearch', 'resolventa'})
WEEK = '2026-W39'
MON, TUE, WED = date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)
FULL = {'client': [Worklog('client', 'SE-1', d, 8 * 3600) for d in (date(2026, 9, 24), date(2026, 9, 25))]}


def at(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=MSK)


def lines_on(lines, day):
    return [x for x in lines if x.day == day and x.key]


def test_round_quarters_keeps_day_sum():
    got = round_quarters({'SE-1': 1000, 'SE-2': 1000, 'SE-3': 1000}, 7 * 3600)
    assert sum(got.values()) == 7 * 3600
    assert all(v % 900 == 0 for v in got.values())
    odd = round_quarters({'SE-1': 5, 'SE-2': 1}, 3600 + 120)
    assert sum(odd.values()) == 3720


def test_activity_blocks_and_tail():
    msgs = [(at(WED, 10), 'green', 'SE-1'), (at(WED, 10, 10), 'green', 'SE-1'),
            (at(WED, 12), 'green', 'SE-2')]
    act = activity(RULES, msgs, WEEK)
    assert act[WED][('green', 'SE-1')] == 600 + 450
    assert act[WED][('green', 'SE-2')] == 450


def test_saturday_moves_to_monday_monday_is_norm():
    sat = MON - timedelta(days=2)
    msgs = [(at(sat, 10), 'green', 'SE-7'), (at(sat, 10, 10), 'green', 'SE-7'),
            (at(MON, 10), 'green', 'SE-1'), (at(MON, 10, 10), 'green', 'SE-1')]
    act = activity(RULES, msgs, WEEK)
    assert sat not in act and ('green', 'SE-7') in act[MON]
    logs = {'client': FULL['client'] + [Worklog('client', 'SE-1', d, 8 * 3600) for d in (TUE, WED)]}
    lines = draft_client(RULES, logs, act, [], WEEK)
    mon = lines_on(lines, MON)
    assert sum(x.seconds for x in mon) == 8 * 3600
    assert {x.key for x in mon} == {'SE-1', 'SE-7'}
    assert all(x.day.weekday() < 5 for x in lines)


def test_manual_se188_first_green_gets_seven_hours():
    act = {WED: {('green', 'SE-1'): 3000, ('green', 'SE-2'): 1000, ('green', 'SE-188'): 500}}
    manual = [{'sheet': 'client', 'day': '2026-09-23', 'key': 'SE-188', 'seconds': 3600, 'comment': 'созвон'}]
    lines = [x for x in lines_on(draft_client(RULES, FULL, act, manual, WEEK), WED)]
    proposed = [x for x in lines if x.source == 'activity']
    assert sum(x.seconds for x in proposed) == 7 * 3600
    assert 'SE-188' not in {x.key for x in proposed}
    assert [(x.key, x.seconds, x.source) for x in lines if x.source == 'manual'] == [('SE-188', 3600, 'manual')]


def test_weekday_without_activity_is_empty_day():
    lines = draft_client(RULES, FULL, {}, [], WEEK)
    assert not lines_on(lines, WED)
    assert [x.flags for x in lines if x.day == WED] == [['empty-day']]


def test_full_day_untouched_and_logged_issue_subtracted():
    logs = {'client': FULL['client'] + [Worklog('client', 'SE-1', MON, 8 * 3600), Worklog('client', 'SE-1', TUE, 4 * 3600)]}
    act = {MON: {('green', 'SE-9'): 3600}, TUE: {('green', 'SE-1'): 3600, ('green', 'SE-2'): 3600}}
    lines = draft_client(RULES, logs, act, [], WEEK)
    assert not [x for x in lines if x.day == MON]
    assert [(x.key, x.seconds) for x in lines_on(lines, TUE)] == [('SE-2', 4 * 3600)]


def test_captivia_activity_not_in_client():
    act = {WED: {('captivia', 'DEV-620'): 3600, ('green', 'SE-1'): 600}}
    assert [(x.key, x.seconds) for x in lines_on(draft_client(RULES, FULL, act, [], WEEK), WED)] == [('SE-1', 8 * 3600)]

CANDS = {'GS': [('GS-11', 'SE-1 a'), ('GS-12', 'SE-2 b'), ('GS-13', 'SE-3 c'), ('GS-1', 'SE-188 Common')],
         'CAP': [('CAP-481', 'DEV-620: отчёт')]}


def emp(lines, day):
    return {x.key: x.seconds for x in lines if x.day == day and x.sheet == 'employer'}


def test_employer_wednesday_green_cut_from_largest():
    client = [Worklog('client', 'SE-1', WED, 4 * 3600), Worklog('client', 'SE-2', WED, 3 * 3600),
              Worklog('client', 'SE-3', WED, 3600)]
    logs = {'client': client, 'employer': []}
    act = {WED: {('ai-pipeline', ''): 3600, ('captivia', 'DEV-620'): 1800}}
    lines = draft_employer(RULES, logs, act, [], [], WEEK, CANDS)
    got = emp(lines, WED)
    assert got['COM-1'] == 3600 and got['CAP-481'] == 1800
    assert got['GS-13'] == 3600
    assert got['GS-11'] + got['GS-12'] + got['GS-13'] == int(6.5 * 3600)
    assert got['GS-11'] < 4 * 3600 and got['GS-12'] < 3 * 3600
    assert sum(got.values()) == 8 * 3600
    assert [x.comment for x in lines if x.key == 'CAP-481'] == ['QA']


def test_employer_projects_without_norm_get_activity_and_manual_se188_mirrored():
    manual = [{'sheet': 'client', 'day': '2026-09-23', 'key': 'SE-188', 'seconds': 3600, 'comment': 'созвон'}]
    act = {WED: {('green', 'SE-1'): 3000, ('ai-pipeline', ''): 2 * 3600 + 100, ('captivia', 'DEV-620'): 900}}
    logs = {'client': FULL['client'], 'employer': []}
    client_lines = draft_client(RULES, logs, act, manual, WEEK)
    got = emp(draft_employer(RULES, logs, act, manual, client_lines, WEEK, CANDS), WED)
    assert got['COM-1'] == 2 * 3600 and got['CAP-481'] == 900
    assert got['GS-1'] == 3600
    assert sum(got.values()) == 8 * 3600


def test_employer_full_day_untouched_logged_subtracted_and_no_mirror():
    logs = {'client': [Worklog('client', 'SE-1', d, 8 * 3600) for d in (MON, TUE)] +
            [Worklog('client', 'SE-7', WED, 8 * 3600)],
            'employer': [Worklog('employer', 'GS-11', MON, 8 * 3600), Worklog('employer', 'GS-11', TUE, 2 * 3600)]}
    lines = draft_employer(RULES, logs, {}, [], [], WEEK, CANDS)
    assert not [x for x in lines if x.day == MON]
    assert emp(lines, TUE) == {'GS-11': 6 * 3600}
    wed = [x for x in lines if x.day == WED]
    assert [(x.key, x.mirror_of, x.seconds, x.flags) for x in wed] == [('', 'SE-7', 8 * 3600, ['no-mirror', 'create-mirror'])]


def test_manual_entry_matches_worklog_by_comment_and_consumes_it_once():
    manual = [{'sheet': 'client', 'day': '2026-09-23', 'key': 'SE-1', 'seconds': 3600, 'comment': c} for c in 'ab']
    foreign = {'client': FULL['client'] + [Worklog('client', 'SE-1', WED, 3600, 'old', '42')]}
    assert [x.sent_id for x in draft_client(RULES, foreign, {}, manual, WEEK) if x.source == 'manual'] == ['', '']
    twice = [manual[0], dict(manual[0])]
    own = {'client': FULL['client'] + [Worklog('client', 'SE-1', WED, 3600, 'a', '42')]}
    assert [x.sent_id for x in draft_client(RULES, own, {}, twice, WEEK) if x.source == 'manual'] == ['42', '']


def test_manual_entry_marked_sent_follows_its_worklog_by_id():
    manual = [{'sheet': 'client', 'day': '2026-09-23', 'key': 'SE-1', 'seconds': 3600, 'comment': 'a', 'sent_id': '42'}]
    edited = {'client': FULL['client'] + [Worklog('client', 'SE-1', WED, 1800, 'a', '42')]}
    assert [x.sent_id for x in draft_client(RULES, edited, {}, manual, WEEK) if x.source == 'manual'] == ['42']
    gone = {'client': FULL['client']}
    assert [x.sent_id for x in draft_client(RULES, gone, {}, manual, WEEK) if x.source == 'manual'] == ['']
