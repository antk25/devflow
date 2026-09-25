from pathlib import Path

import pytest

from devflow.timesheet import JiraError, ensure_mirror, find_mirror, load_rules

EXAMPLE = Path(__file__).resolve().parents[1] / 'skills/timesheet/timesheet.example.json'
RULES = load_rules(EXAMPLE, {'productsearch', 'resolventa'})
GS = next(r for r in RULES.projects if r.jira_project == 'GS')
CAP = next(r for r in RULES.projects if r.jira_project == 'CAP')


def test_mirror_by_summary_prefix():
    gs = [('GS-1243', 'SE-2158 Search facets'), ('GS-1244', 'SE-21580 Other'), ('GS-1', 'SE-188 Common task')]
    assert find_mirror('SE-2158', GS, gs) == ('GS-1243', '')
    cap = [('CAP-481', 'DEV-620: Отчёт'), ('CAP-482', 'DEV-62 Другое')]
    assert find_mirror('DEV-620', CAP, cap) == ('CAP-481', '')


def test_manual_mapping_wins_and_missing_flagged():
    assert find_mirror('SE-2045', GS, [('GS-9', 'SE-2045 dup')]) == ('GS-1214', '')
    assert find_mirror('SE-7', GS, []) == ('', 'no-mirror')
    assert find_mirror('SE-7', GS, None) == ('', 'mirror-unavailable')


def test_two_candidates_ambiguous():
    assert find_mirror('SE-5', GS, [('GS-1', 'SE-5 a'), ('GS-2', 'SE-5: b')]) == ('', 'ambiguous-mirror')


class _Proc:
    def __init__(self, stdout='', returncode=0, stderr=''):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def _jira(gs):
    def call(script, *args):
        if 'project = GS' in args:
            return [{'key': k, 'fields': {'summary': s}} for k, s in gs]
        return [{'key': 'SE-2300', 'fields': {'summary': 'Search facets broken'}}]
    return call


def _mirror(gs, yes, runs):
    def run(args, **kw):
        runs.append(args)
        return _Proc('GS-1300 https://r/browse/GS-1300\n' if '--yes' in args else '{"fields": {}}\n')
    return ensure_mirror(RULES, 'SE-2300', yes, call=_jira(gs), run=run, base_url=lambda a: 'https://p.example')


def test_existing_mirror_creates_nothing_and_is_stable():
    runs = []
    gs = [('GS-1260', 'SE-2300 Search facets broken')]
    assert _mirror(gs, True, runs)[:2] == ('GS-1260', False)
    assert _mirror(gs, True, runs)[:2] == ('GS-1260', False)
    assert runs == []


def test_missing_mirror_dry_run_does_not_create():
    runs = []
    key, created, text = _mirror([], False, runs)
    assert (key, created) == ('', False)
    [args] = runs
    assert '--yes' not in args
    assert args[args.index('-s') + 1] == 'SE-2300 Search facets broken'
    assert args[args.index('-a') + 1] == 'me' and args[args.index('-P') + 1] == 'GS'
    assert 'будет создано' in text


def test_missing_mirror_created_with_yes():
    runs = []
    assert _mirror([], True, runs)[:2] == ('GS-1300', True)
    assert '--yes' in runs[0]


def test_ambiguous_mirror_refused():
    with pytest.raises(JiraError, match='ambiguous-mirror'):
        _mirror([('GS-1', 'SE-2300 a'), ('GS-2', 'SE-2300 b')], True, [])
