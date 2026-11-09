import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'scripts' / 'devflow-cli.sh'
S1 = 's1aaaaaaaa-session'


@pytest.fixture
def env(tmp_path):
    home, vault, repo = tmp_path / 'home', tmp_path / 'vault', tmp_path / 'repo'
    for d in (home / '.claude' / 'devflow', vault / 'notes', vault / 'tz', repo):
        d.mkdir(parents=True)
    (vault / 'tz' / 'df-1-x.md').write_text('# X\n', encoding='utf-8')
    (repo / 'AGENTS.md').write_text(f'---\nproject: p\nvault: {vault}\n---\n', encoding='utf-8')
    git = lambda *a: subprocess.run(['git', '-C', str(repo), *a], check=True, capture_output=True)
    git('init', '-q', '-b', 'main')
    git('-c', 'user.email=a@b', '-c', 'user.name=a', 'commit', '-q', '--allow-empty', '-m', 'init')
    return {'home': home, 'vault': vault, 'repo': repo, 'git': git}


def ledger(env, task, session=S1):
    (env['home'] / '.claude/devflow/task-ledger.jsonl').write_text(
        json.dumps({'ts': '2026-11-09T10:00:00', 'session': session, 'task': task}) + '\n', encoding='utf-8')


def run(env, *args):
    out = subprocess.run([str(CLI), '--cwd', str(env['repo']), *args], capture_output=True, text=True,
                         env={'PATH': os.environ['PATH'], 'HOME': str(env['home'])})
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def auto(env, trigger='auto', session=S1):
    return run(env, 'handoff', 'auto', '--session', session, '--trigger', trigger,
               '--context-tokens', '190000', '--host', 'claude')


@pytest.mark.parametrize('trigger', ['auto', 'manual'])
def test_creates_handoff_from_ledger(env, trigger):
    ledger(env, 'DF-1')
    result = auto(env, trigger)
    path = env['vault'] / 'notes' / 'handoff-df-1-x.md'
    assert result['action'] == 'created' and result['path'] == str(path)
    text = path.read_text(encoding='utf-8')
    for part in ('type: handoff', 'task: df-1-x', f'session: {S1}', 'Ветка: `main`',
                 'записано автоматически'.capitalize(), f'({trigger})'):
        assert part in text
    assert str(path) in result['instructions'] and 'тупики' in result['instructions']


def test_appends_to_own_session_handoff(env):
    ledger(env, 'DF-1')
    path = env['vault'] / 'notes' / 'handoff-df-1-x.md'
    before = f'---\ntype: handoff\ntask: df-1-x\nsession: {S1}\n---\n\n# Ручная\n\n## Тупики\n- x\n'
    path.write_text(before, encoding='utf-8')
    assert auto(env)['action'] == 'appended'
    after = path.read_text(encoding='utf-8')
    assert after.startswith(before) and '## Автоматически при сжатии' in after[len(before):]


@pytest.mark.parametrize('session_line', ['session: s0\n', ''])
def test_foreign_handoff_untouched(env, session_line):
    ledger(env, 'DF-1')
    path = env['vault'] / 'notes' / 'handoff-df-1-x.md'
    before = f'---\ntype: handoff\ntask: df-1-x\n{session_line}---\n\n# Чужая\n'
    path.write_text(before, encoding='utf-8')
    result = auto(env)
    assert path.read_bytes() == before.encode('utf-8')
    assert result['path'] == str(env['vault'] / 'notes' / f'handoff-df-1-x-auto-{S1[:8]}.md')
    assert result['action'] == 'created'


def test_branch_fallback_and_main(env):
    assert auto(env)['action'] == 'none'
    assert list((env['vault'] / 'notes').iterdir()) == []
    env['git']('checkout', '-q', '-b', 'feat/df-1-x')
    result = auto(env)
    assert result['slug'] == 'df-1-x' and result['action'] == 'created'
    assert run(env, 'handoff', 'slug', '--session', 'other')['slug'] == 'df-1-x'


def test_none_without_path_in_instructions(env):
    result = auto(env)
    assert result['path'] is None and 'notes/' not in result['instructions']


def test_foreign_key_creates_nothing(env):
    ledger(env, 'SE-9')
    assert auto(env)['action'] == 'none'
    assert list((env['vault'] / 'notes').iterdir()) == []


def test_compact_log(env):
    ledger(env, 'DF-1')
    auto(env)
    entry = json.loads((env['home'] / '.claude/devflow/compact-log.jsonl').read_text().splitlines()[-1])
    assert entry['host'] == 'claude' and entry['session'] == S1
    assert entry['trigger'] == 'auto' and entry['tokens'] == 190000 and entry['slug'] == 'df-1-x'


def test_handoff_slug_from_ledger(env):
    ledger(env, 'DF-1')
    assert run(env, 'handoff', 'slug', '--session', S1)['slug'] == 'df-1-x'


def test_latest_treats_auto_handoff_as_same_task(env):
    notes = env['vault'] / 'notes'
    (notes / 'handoff-df-1-x.md').write_text('---\ncreated: 2026-11-01\ntype: handoff\ntask: df-1-x\n---\n', encoding='utf-8')
    newer = notes / f'handoff-df-1-x-auto-{S1[:8]}.md'
    newer.write_text('---\ncreated: 2026-11-09\ntype: handoff\ntask: df-1-x\n---\n', encoding='utf-8')
    assert run(env, 'handoff', 'latest', '--task', 'df-1')['path'] == str(newer)


def test_context_level(env):
    cut = run(env, 'context-level', '--tokens', '185000', '--session', 's1')
    assert cut['level'] == 'cut' and cut['text'].startswith('CONTEXT_CUT 185K')
    assert 'без спроса' in cut['text'] and 's1' in cut['text']
    assert run(env, 'context-level', '--tokens', '125000')['level'] == 'warn'
    assert run(env, 'context-level', '--tokens', '100000', '--window', '120000')['level'] == 'warn'
    assert run(env, 'context-level', '--tokens', '100000')['level'] == 'ok'
