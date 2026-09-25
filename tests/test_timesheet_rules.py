import json
from datetime import date

import pytest

from devflow.timesheet import RulesError, load_rules, msk_day, week_range

EXAMPLE = __import__('pathlib').Path(__file__).resolve().parents[1] / 'skills/timesheet/timesheet.example.json'
ACCOUNTS = {'productsearch', 'resolventa'}


def test_both_sites_offsets_give_same_msk_day():
    assert msk_day('2026-09-15T23:00:00.000+0200') == date(2026, 9, 16)
    assert msk_day('2026-09-16T00:00:00.000-0500') == date(2026, 9, 16)
    assert msk_day('2026-09-15T23:00:00+0200') == msk_day('2026-09-16T00:00:00-0500')


def test_week_range():
    assert week_range('W38', today=date(2026, 9, 25)) == (date(2026, 9, 14), date(2026, 9, 20))
    assert week_range('2025-W01') == (date(2024, 12, 30), date(2025, 1, 5))


def test_example_loads():
    rules = load_rules(EXAMPLE, ACCOUNTS)
    assert set(rules.sheets) == {'client', 'employer'}
    assert rules.project_of('employer', 'COM-1') == 'ai-pipeline'
    assert rules.project_of('employer', 'COM-2') is None
    assert rules.project_of('client', 'GS-1') is None


def _write(tmp_path, mutate):
    raw = json.loads(EXAMPLE.read_text())
    mutate(raw)
    p = tmp_path / 'rules.json'
    p.write_text(json.dumps(raw))
    return p


def test_unknown_account_names_sheet_and_field(tmp_path):
    p = _write(tmp_path, lambda r: r['sheets']['employer'].update(account='nope'))
    with pytest.raises(RulesError, match=r'^employer\.account: .*nope'):
        load_rules(p, ACCOUNTS)


def test_unknown_sheet_names_project_and_field(tmp_path):
    p = _write(tmp_path, lambda r: r['projects']['captivia'].update(boss={'jira_project': 'CAP'}))
    with pytest.raises(RulesError, match=r'^captivia\.boss: неизвестный табель'):
        load_rules(p, ACCOUNTS)


def test_bad_norm(tmp_path):
    p = _write(tmp_path, lambda r: r['sheets']['client'].update(day_hours=0))
    with pytest.raises(RulesError, match=r'^client\.day_hours'):
        load_rules(p, ACCOUNTS)
