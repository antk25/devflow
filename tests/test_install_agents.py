import os
import shutil
import subprocess
from pathlib import Path

import pytest

from devflow import policy
from devflow.project import ROOT

MARKER = policy.MARKER_KEY


@pytest.fixture
def home(tmp_path):
    (tmp_path / 'home/.claude').mkdir(parents=True)
    # settings drift is checked by --check too; keep it green so only agent state decides the exit code
    text = (ROOT / 'settings.global.example.json').read_text().replace('__DEVFLOW_ROOT__', str(ROOT))
    (tmp_path / 'home/.claude/settings.json').write_text(text)
    return tmp_path / 'home'


def env(home):
    e = dict(os.environ)
    e.update(HOME=str(home), DEVFLOW_CLAUDE_DIR=str(home / '.claude'), DEVFLOW_BIN_DIR=str(home / 'bin'),
             DEVFLOW_INTEGRATIONS_DIR=str(home / 'integrations'), DEVFLOW_PI_DIR=str(home / 'pi'),
             DEVFLOW_MODEL_POLICY=str(home / 'model-policy.json'))
    e.pop('DEVFLOW_STATE_DIR', None)
    return e


def install(home, *args):
    return subprocess.run(['bash', str(ROOT / 'install.sh'), *args], env=env(home), capture_output=True, text=True)


def agents(home):
    return home / '.claude/agents'


def test_install_generates_phase_agents_and_links_the_rest(home):
    r = install(home)
    assert r.returncode == 0, r.stdout + r.stderr
    generated = sorted(p.name for p in agents(home).iterdir() if p.is_file() and not p.is_symlink())
    assert generated == ['implement.md', 'plan-high.md', 'plan.md', 'research-high.md', 'research.md']
    linked = sorted(p.name for p in agents(home).iterdir() if p.is_symlink())
    assert linked == ['crossreview.md', 'review-conformance.md', 'review-standards.md']
    text = (agents(home) / 'research-high.md').read_text()
    assert 'name: research-high\n' in text and 'model: claude-opus-5-5\n' in text and 'effort: high\n' in text
    assert text.split('---\n', 2)[2].startswith('<!-- ' + MARKER)
    assert (agents(home) / 'implement.md').read_text().count('model: claude-fable-5-1') == 1
    assert not list(agents(home).glob('*.tmp'))


def test_second_run_is_idempotent(home):
    assert install(home).returncode == 0
    before = {p.name: p.read_text() for p in agents(home).iterdir()}
    r = install(home)
    assert r.returncode == 0
    assert {p.name: p.read_text() for p in agents(home).iterdir()} == before
    assert 'generate ' not in r.stdout
    r = install(home, '--check')
    assert r.returncode == 0 and 'STALE' not in r.stdout, r.stdout


def test_old_symlink_to_our_source_is_replaced(home):
    agents(home).mkdir(parents=True)
    (agents(home) / 'plan.md').symlink_to(ROOT / 'agents/plan.md')
    r = install(home)
    assert r.returncode == 0, r.stderr
    assert not (agents(home) / 'plan.md').is_symlink() and MARKER in (agents(home) / 'plan.md').read_text()


def test_foreign_research_file_is_a_conflict(home):
    agents(home).mkdir(parents=True)
    (agents(home) / 'research.md').write_text('---\nname: research\n---\nmine\n')
    r = install(home)
    assert r.returncode == 1
    assert 'CONFLICT (not replacing): ' + str(agents(home) / 'research.md') in r.stderr
    assert (agents(home) / 'research.md').read_text().endswith('mine\n')
    assert not (agents(home) / 'plan.md').exists()


def test_check_reports_stale_after_policy_edit(home):
    assert install(home).returncode == 0
    p = home / 'model-policy.json'
    p.write_text(p.read_text().replace('"effort": "low"', '"effort": "medium"', 1))
    r = install(home, '--check')
    assert r.returncode == 1
    assert 'STALE agent implement' in r.stdout
    assert 'STALE agent plan' not in r.stdout
    assert 'ok ' + str(agents(home) / 'plan.md') in r.stdout and 'ok ' + str(agents(home) / 'implement.md') not in r.stdout
    assert 'ok ' + str(p) in r.stdout
    r = install(home)
    assert r.returncode == 0 and 'generate ' + str(agents(home) / 'implement.md') in r.stdout
    r = install(home, '--check')
    assert r.returncode == 0 and 'STALE' not in r.stdout, r.stdout


def test_check_reports_missing_agent(home):
    assert install(home).returncode == 0
    (agents(home) / 'plan-high.md').unlink()
    r = install(home, '--check')
    assert r.returncode == 1 and 'STALE agent plan-high' in r.stdout


def test_remove_deletes_only_generated_files(home):
    assert install(home).returncode == 0
    (agents(home) / 'mine.md').write_text('keep\n')
    r = install(home, '--remove')
    assert r.returncode == 0
    assert sorted(p.name for p in agents(home).iterdir()) == ['mine.md']


def test_check_flags_statusline_without_rate_limits_call(home):
    assert install(home).returncode == 0
    assert (home / 'bin/devflow-rate-limits').is_symlink()
    statusline = home / '.claude/statusline.sh'
    statusline.write_text('#!/usr/bin/env bash\ninput=$(cat)\n')
    r = install(home, '--check')
    assert r.returncode == 1 and 'MISS statusline call devflow-rate-limits' in r.stdout
    statusline.write_text('#!/usr/bin/env bash\ninput=$(cat)\necho "$input" | devflow-rate-limits\n')
    r = install(home, '--check')
    assert r.returncode == 0 and 'MISS statusline' not in r.stdout
