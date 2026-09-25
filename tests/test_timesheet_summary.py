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
