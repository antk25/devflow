import os
import subprocess
import sys
from pathlib import Path

import pytest

from devflow import pi
from devflow.documents import WorkflowError

ROOT = Path(__file__).resolve().parents[1]
SLUG = 'pi-smoke-unit'
MESSAGE = (f'Скилл: {ROOT}/skills/smoke/SKILL.md\nАргументы: slug: {SLUG}; env: local; Проверить\n'
           f'Вердикт: /tmp/devflow-smoke/{SLUG}/verdict.md')


@pytest.fixture
def smoke(tmp_path):
    env = {**os.environ, 'DEVFLOW_SMOKE_DIR': str(tmp_path / 'smoke')}
    verdict = tmp_path / 'smoke' / SLUG / 'verdict.md'
    return env, verdict


def execute(smoke, script, timeout=3):
    env, _ = smoke
    return pi._browser_process([sys.executable, '-c', script], {'cwd': ROOT}, MESSAGE, env, timeout)


def test_new_scenario_removes_old_verdict_and_cleans(smoke):
    env, verdict = smoke
    verdict.parent.mkdir(parents=True)
    verdict.write_text('old success')
    script = f'from pathlib import Path; p=Path({str(verdict)!r}); assert not p.exists(); p.write_text("## Вердикт: 1/1 ✅\\n")'
    result = execute(smoke, script)
    assert result.returncode == 0, result.stderr
    assert verdict.read_text().startswith('## Вердикт:')


@pytest.mark.parametrize('script', ['raise SystemExit(7)', 'print("✅")', 'import time; time.sleep(10)'])
def test_exit_empty_verdict_and_timeout_not_success(smoke, script):
    result = execute(smoke, script, timeout=0.3)
    assert result.returncode != 0
    assert not smoke[1].exists()


def test_nonzero_exit_discards_even_success_verdict(smoke):
    verdict = smoke[1]
    result = execute(smoke, f'from pathlib import Path; Path({str(verdict)!r}).write_text("## Вердикт: 1/1 ✅"); raise SystemExit(8)')
    assert result.returncode == 8
    assert not verdict.exists()


def test_missing_slug_before_start(smoke):
    with pytest.raises(WorkflowError, match='slug'):
        pi._browser_process(['never-execute'], {'cwd': ROOT}, 'Вердикт: /tmp/wrong', smoke[0], 1)


def test_claude_fork_agent_and_secrets_contract():
    skill = (ROOT / 'skills/smoke/SKILL.md').read_text()
    implement = (ROOT / 'agents/implement.md').read_text()
    browser = (ROOT / 'agents/browser.md').read_text()
    assert 'context: fork\nagent: browser' in skill
    assert 'Agent(subagent_type: "browser"' in implement
    assert 'exit 3' in implement and 'exit 124' in implement
    assert 're-run the same line once' in implement
    assert '@env:ИМЯ' in skill and '@env:NAME' not in browser
    assert 'browser.env` не читать' in browser
    assert 'set -euo pipefail' in skill and 'exit $fail' in skill
    assert 'значения не печатать' in browser


@pytest.mark.parametrize('kind,expected', [('stale', 3), ('limit', 124)])
def test_wait_deadline_on_fake_clock(tmp_path, kind, expected):
    tools = tmp_path / 'tools'
    tools.mkdir()
    count = tmp_path / 'clock'
    (tools / 'date').write_text(f'#!/bin/bash\nn=$(<"{count}")\necho $((n+421)) > "{count}"\necho "$n"\n')
    count.write_text('1000')
    (tools / 'stat').write_text('#!/bin/bash\necho ' + ('1000' if kind == 'stale' else '1421') + '\n')
    (tools / 'pgrep').write_text('#!/bin/bash\nexit 1\n')
    for tool in tools.iterdir():
        tool.chmod(0o755)
    env = {**os.environ, 'PATH': f'{tools}:{os.environ["PATH"]}', 'DEVFLOW_SMOKE_DIR': str(tmp_path / 'smoke')}
    result = subprocess.run([str(ROOT / 'bin/devflow-smoke-wait'), 'wait', 'demo'],
                            env=env, capture_output=True, text=True, timeout=2)
    assert result.returncode == expected, result.stderr


def test_stop_task_only_stops_matching_sessions(tmp_path):
    tools = tmp_path / 'tools'
    tools.mkdir()
    log = tmp_path / 'calls'
    (tools / 'npx').write_text(f'#!/bin/bash\nprintf "%s " "$@" >> "{log}"\n')
    (tools / 'npx').chmod(0o755)
    sessions = tmp_path / 'smoke/.sessions'
    sessions.mkdir(parents=True)
    (sessions / 'abc-123').write_text('demo')
    (sessions / 'abc-456').write_text('other')
    env = {**os.environ, 'PATH': f'{tools}:{os.environ["PATH"]}', 'DEVFLOW_SMOKE_DIR': str(sessions.parent)}
    result = subprocess.run([str(ROOT / 'bin/devflow-browser'), 'stop-task', 'demo'],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not (sessions / 'abc-123').exists()
    assert (sessions / 'abc-456').exists()
    assert 'stop --sessionId abc-123' in log.read_text()
    assert 'abc-456' not in log.read_text()


def test_pi_browser_uses_literal_sessions_without_guard_bypass():
    skill = (ROOT / 'skills/smoke/SKILL.md').read_text()
    browser = (ROOT / 'agents/browser.md').read_text()
    for text in (skill, browser):
        assert 'буквально' in text
        assert 'составных команд' in text or 'составные команды' in text
        assert 'Guard не ослаблять и не обходить' in text
        assert 'требует подтверждения' in text
        assert 'Не хватает' in text


def test_save_replay_exit_and_failure_contract():
    skill = (ROOT / 'skills/smoke/SKILL.md').read_text()
    assert 'ненулевой exit даже без ❌' in skill
    assert 'smoke-<slug>.sh' in skill and 'секреты — `@env:ИМЯ`' in skill
    assert 'stop >/dev/null 2>&1 || rc=1' in skill
