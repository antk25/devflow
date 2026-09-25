from pathlib import Path

from devflow.timesheet import find_mirror, load_rules

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
