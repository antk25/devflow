from datetime import date
from pathlib import Path

from devflow.timesheet import JiraError, Unavailable, Worklog, fetch_worklogs, load_rules, summary

EXAMPLE = Path(__file__).resolve().parents[1] / 'skills/timesheet/timesheet.example.json'
RULES = load_rules(EXAMPLE, {'productsearch', 'resolventa'})
WEEK = '2026-W38'
MON = date(2026, 9, 14)


def test_project_outside_rules_is_dropped():
    logs = {'client': [Worklog('client', 'SE-1', MON, 3600)],
            'employer': [Worklog('employer', 'GS-5', MON, 1800), Worklog('employer', 'DF-16', MON, 7200),
                         Worklog('employer', 'COM-1', MON, 900)]}
    s = summary(RULES, logs, WEEK)
    assert s['employer']['total'] == 2700
    assert set(s['employer']['projects']) == {'green', 'ai-pipeline'}
    assert s['client']['days'][MON] == 3600
    assert date(2026, 9, 15) in s['client']['empty'] and MON not in s['client']['empty']


def test_failed_account_is_unavailable_other_sheet_counted():
    def call(script, *args):
        if 'resolventa' in args:
            raise JiraError('401 Unauthorized')
        if script == 'jira-jql.sh':
            return [{'key': 'SE-1'}]
        return [{'total': 3, 'worklogs': [
            {'id': 1, 'started': '2026-09-13T23:00:00.000+0200', 'timeSpentSeconds': 3600,
             'author': {'accountId': '<accountId>'}},
            {'id': 2, 'started': '2026-09-13T20:00:00.000+0200', 'timeSpentSeconds': 600,
             'author': {'accountId': '<accountId>'}},
            {'id': 3, 'started': '2026-09-14T10:00:00.000+0200', 'timeSpentSeconds': 999,
             'author': {'accountId': 'someone'}}]}]

    logs = fetch_worklogs(RULES, WEEK, call)
    assert isinstance(logs['employer'], Unavailable)
    s = summary(RULES, logs, WEEK)
    assert s['employer'] == {'unavailable': '401 Unauthorized'}
    assert s['client']['total'] == 3600 and s['client']['days'][MON] == 3600


def test_worklog_error_body_makes_sheet_unavailable_not_empty():
    def call(script, *args):
        if script == 'jira-jql.sh':
            return [{'key': 'SE-1'}]
        return [{'errorMessages': ['Issue does not exist or you do not have permission to see it.']}]

    logs = fetch_worklogs(RULES, WEEK, call)
    assert isinstance(logs['client'], Unavailable)
    assert 'permission' in logs['client'].reason


def test_w38_discrepancies_issue_without_pair_and_day_mismatch():
    from devflow.timesheet import discrepancies, render_discrepancies
    tue = date(2026, 9, 15)
    logs = {'client': [Worklog('client', 'SE-2158', MON, 6 * 3600), Worklog('client', 'SE-2141', MON, 2 * 3600),
                       Worklog('client', 'SE-2158', tue, 8 * 3600)],
            'employer': [Worklog('employer', 'GS-1243', MON, 7 * 3600), Worklog('employer', 'COM-1', MON, 3600),
                         Worklog('employer', 'GS-1243', tue, 7 * 3600), Worklog('employer', 'COM-1', tue, 3600),
                         Worklog('employer', 'GS-1300', tue, 900)]}
    cands = {'GS': [('GS-1243', 'SE-2158 Поиск'), ('GS-1300', 'SE-2199 Другое')]}
    out = discrepancies(RULES, logs, cands, WEEK)
    missing = [x for x in out if x['kind'] == 'missing']
    assert {(x['key'], x['sheet'], x['pair']) for x in missing} == {('SE-2141', 'employer', ''),
                                                                 ('GS-1300', 'client', 'SE-2199')}
    days = {x['day']: x['diff'] for x in out if x['kind'] == 'day'}
    assert days == {tue: 900}
    assert 'SE-2141' in render_discrepancies(out)


def test_no_discrepancies_when_sheets_agree():
    from devflow.timesheet import discrepancies, render_discrepancies
    logs = {'client': [Worklog('client', 'SE-2045', MON, 8 * 3600)],
            'employer': [Worklog('employer', 'GS-1214', MON, 6 * 3600), Worklog('employer', 'CAP-1', MON, 7200)]}
    assert discrepancies(RULES, logs, {'GS': []}, WEEK) == []
    assert render_discrepancies([]) == 'Расхождений между табелями нет'
