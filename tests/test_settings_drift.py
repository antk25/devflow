import json
import shutil

from devflow.project import ROOT, guard_probe, settings_drift

EXAMPLE = ROOT / 'settings.global.example.json'


def test_missing_actual_reports_everything(tmp_path):
    wanted = json.loads(EXAMPLE.read_text())
    drift = settings_drift(tmp_path / 'settings.json', EXAMPLE)
    assert drift['hooks'] == [
        'PreToolUse ' + wanted['hooks']['PreToolUse'][0]['hooks'][0]['command'],
        'SessionStart ' + wanted['hooks']['SessionStart'][0]['hooks'][0]['command'],
    ]
    assert drift['allow'] == wanted['permissions']['allow']
    assert drift['ask'] == wanted['permissions']['ask']
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
    assert settings_drift(actual, EXAMPLE) == {'hooks': [], 'allow': [], 'ask': [], 'deny': [], 'extra_deny': []}


def test_hook_matched_by_script_name_with_real_root(tmp_path):
    actual = tmp_path / 'settings.json'
    data = json.loads(EXAMPLE.read_text())
    data['hooks']['SessionStart'][0]['hooks'][0]['command'] = f"bash '{ROOT}/.claude/hooks/project-restore.sh'"
    actual.write_text(json.dumps(data))
    assert settings_drift(actual, EXAMPLE)['hooks'] == []


def test_stale_gh_deny_reported(tmp_path):
    actual = tmp_path / 'settings.json'
    data = json.loads(EXAMPLE.read_text())
    data['permissions']['deny'] += ['Bash(gh:*)', 'Bash(nc:*)']
    actual.write_text(json.dumps(data))
    drift = settings_drift(actual, EXAMPLE)
    assert drift['extra_deny'] == ['Bash(gh:*)']
    assert drift['deny'] == []


def test_missing_lcurl_curl_wget_reported(tmp_path):
    actual = tmp_path / 'settings.json'
    data = json.loads(EXAMPLE.read_text())
    data['permissions']['allow'].remove('Bash(lcurl:*)')
    data['permissions']['deny'] = [r for r in data['permissions']['deny'] if r not in ('Bash(curl:*)', 'Bash(wget:*)')]
    actual.write_text(json.dumps(data))
    drift = settings_drift(actual, EXAMPLE)
    assert drift['allow'] == ['Bash(lcurl:*)']
    assert drift['deny'] == ['Bash(curl:*)', 'Bash(wget:*)']


def _with_guard(tmp_path, command):
    actual = tmp_path / 'settings.json'
    data = json.loads(EXAMPLE.read_text())
    data['hooks']['SessionStart'][0]['hooks'][0]['command'] = f"{ROOT}/.claude/hooks/project-restore.sh"
    if command is None:
        del data['hooks']['PreToolUse']
    else:
        data['hooks']['PreToolUse'][0]['hooks'][0]['command'] = command
    actual.write_text(json.dumps(data))
    return actual


def test_missing_guard_reported(tmp_path):
    actual = _with_guard(tmp_path, None)
    assert settings_drift(actual, EXAMPLE)['hooks'] == ['PreToolUse __DEVFLOW_ROOT__/scripts/devflow-cli.sh guard']
    assert guard_probe(actual) == []


def test_guard_on_missing_path_is_broken(tmp_path):
    command = f'{tmp_path}/nowhere/scripts/devflow-cli.sh guard'
    actual = _with_guard(tmp_path, command)
    assert settings_drift(actual, EXAMPLE)['hooks'] == []
    assert guard_probe(actual) == [command]


def test_working_guard_reports_nothing(tmp_path):
    actual = _with_guard(tmp_path, f'{ROOT}/scripts/devflow-cli.sh guard')
    assert settings_drift(actual, EXAMPLE)['hooks'] == []
    assert guard_probe(actual) == []


def test_missing_worklog_ask_reported(tmp_path):
    actual = tmp_path / 'settings.json'
    data = json.loads(EXAMPLE.read_text())
    rule = 'Bash(bash ~/.config/devflow/integrations/jira-worklog.sh * --yes*)'
    data['permissions']['ask'].remove(rule)
    actual.write_text(json.dumps(data))
    assert settings_drift(actual, EXAMPLE)['ask'] == [rule]
