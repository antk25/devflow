import json
import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/rate-limits.sh'


def run(tmp_path, payload):
    out = tmp_path / 'devflow/rate-limits.json'
    env = {**os.environ, 'DEVFLOW_RATE_LIMITS': str(out)}
    r = subprocess.run(['bash', str(SCRIPT)], input=payload, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def test_no_rate_limits_field_writes_nothing(tmp_path):
    out = run(tmp_path, json.dumps({'model': {'id': 'claude-fable-5-1'}, 'context_window': {}}))
    assert not out.exists() and not list(tmp_path.glob('**/*.tmp'))


def test_broken_json_writes_nothing(tmp_path):
    assert not run(tmp_path, '{"rate_limits": ').exists()


def test_writes_both_windows_model_and_at(tmp_path):
    before = int(time.time())
    out = run(tmp_path, json.dumps({
        'model': {'id': 'claude-fable-5-1', 'display_name': 'Fable'},
        'rate_limits': {'five_hour': {'used_percentage': 97, 'resets_at': before + 3600},
                        'seven_day': {'used_percentage': 40, 'resets_at': before + 86400}}}))
    data = json.loads(out.read_text())
    assert data['five_hour'] == {'used_percentage': 97, 'resets_at': before + 3600}
    assert data['seven_day']['used_percentage'] == 40
    assert data['model'] == 'claude-fable-5-1'
    assert before <= data['at'] <= int(time.time())
    assert not list(tmp_path.glob('**/*.tmp'))


def test_default_path_under_claude_dir(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != 'DEVFLOW_RATE_LIMITS'}
    env['DEVFLOW_CLAUDE_DIR'] = str(tmp_path / 'claude')
    subprocess.run(['bash', str(SCRIPT)], input=json.dumps({'rate_limits': {'five_hour': {'used_percentage': 1}}}),
                   env=env, capture_output=True, text=True, check=True)
    assert (tmp_path / 'claude/devflow/rate-limits.json').is_file()
