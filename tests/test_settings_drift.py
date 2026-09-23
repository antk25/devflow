import json
import shutil

from devflow.project import ROOT, settings_drift

EXAMPLE = ROOT / 'settings.global.example.json'


def test_missing_actual_reports_everything(tmp_path):
    wanted = json.loads(EXAMPLE.read_text())
    drift = settings_drift(tmp_path / 'settings.json', EXAMPLE)
    assert drift['hooks'] == [wanted['hooks']['SessionStart'][0]['hooks'][0]['command']]
    assert drift['allow'] == wanted['permissions']['allow']
    assert drift['deny'] == wanted['permissions']['deny']
    assert drift['extra_deny'] == []


def test_empty_file_reports_everything(tmp_path):
    actual = tmp_path / 'settings.json'
    actual.write_text('{}')
    drift = settings_drift(actual, EXAMPLE)
    assert drift['hooks'] and drift['allow'] and drift['deny'] and drift['extra_deny'] == []


def test_copy_of_example_has_no_drift(tmp_path):
    actual = tmp_path / 'settings.json'
    shutil.copy(EXAMPLE, actual)
    assert settings_drift(actual, EXAMPLE) == {'hooks': [], 'allow': [], 'deny': [], 'extra_deny': []}


def test_hook_matched_by_script_name_with_real_root(tmp_path):
    actual = tmp_path / 'settings.json'
    data = json.loads(EXAMPLE.read_text())
    data['hooks']['SessionStart'][0]['hooks'][0]['command'] = f"bash '{ROOT}/.claude/hooks/project-restore.sh'"
    actual.write_text(json.dumps(data))
    assert settings_drift(actual, EXAMPLE)['hooks'] == []


def test_stale_gh_deny_reported(tmp_path):
    actual = tmp_path / 'settings.json'
    data = json.loads(EXAMPLE.read_text())
    data['permissions']['deny'] += ['Bash(gh:*)', 'Bash(curl:*)']
    actual.write_text(json.dumps(data))
    drift = settings_drift(actual, EXAMPLE)
    assert drift['extra_deny'] == ['Bash(gh:*)']
    assert drift['deny'] == []
