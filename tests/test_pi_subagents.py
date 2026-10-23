import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile

import pytest

from devflow.pi import agent_body

ROOT = Path(__file__).resolve().parents[1]


def snapshot(root):
    files = {}
    for path in sorted(root.rglob('*')):
        name = str(path.relative_to(root))
        if path.is_symlink():
            files[name] = ('link', os.readlink(path))
        elif path.is_file():
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


@pytest.fixture(scope='module')
def guarded():
    package = os.environ.get('DEVFLOW_SUBAGENTS_PILOT_PACKAGE')
    if not package:
        pytest.fail('Нужен явный DEVFLOW_SUBAGENTS_PILOT_PACKAGE проверенного pi-subagents@0.80.0')
    executable = shutil.which('pi')
    assert executable and shutil.which('node'), 'Нужны установленный Pi и Node'
    sdk = Path(executable).resolve().parents[2]
    loader = sdk / 'dist/core/extensions/loader.js'
    assert loader.is_file()
    evidence_root = Path.home() / '.local/state/devflow/pi-subagents-pilot'
    evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    external = Path(tempfile.mkdtemp(prefix='guarded-', dir=evidence_root))
    cwd = external / 'project'
    home = external / 'home'
    vault = external / 'vault'
    for path in (cwd, home, vault):
        path.mkdir(mode=0o700)
    (home / '.claude').mkdir()
    (home / '.claude/settings.json').write_text(json.dumps({'permissions': {'deny': [
        'Read(**/guard-denied.txt)', 'Grep(**/guard-denied.txt)',
        'Grep(**/guard-denied-dir)', 'Glob(**/guard-denied-dir)',
    ]}}))
    instructions = external / 'instructions.md'
    instructions.write_text('DEVFLOW_TEST_SHARED_INSTRUCTIONS\nТолько фиктивные данные.\n')
    (cwd / 'AGENTS.md').write_text(f'---\nproject: guarded-fixture\nvault: {vault}\n---\n# Fixture\n')
    (cwd / 'safe.txt').write_text('FIXTURE_CONTENT\n')
    (cwd / 'guard-denied.txt').write_text('Не читать\n')
    (cwd / 'guard-denied-dir').mkdir()
    (cwd / 'guard-denied-dir/item.txt').write_text('Не искать\n')
    subprocess.run(['git', 'init', '-b', 'fixture', str(cwd)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(cwd), 'add', 'AGENTS.md', 'safe.txt', 'guard-denied.txt'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(cwd), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '-m', 'fixture'], check=True, capture_output=True)
    base = subprocess.run(['git', '-C', str(cwd), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
    (cwd / 'safe.txt').write_text('FIXTURE_CONTENT\nSECOND_COMMIT\n')
    subprocess.run(['git', '-C', str(cwd), 'add', 'safe.txt'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(cwd), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                    'commit', '-m', 'fixture second'], check=True, capture_output=True)
    head = subprocess.run(['git', '-C', str(cwd), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()
    (cwd / 'untracked.txt').write_text('Сохраняется\n')
    (cwd / '.env').write_text('FAKE_ONLY=1\n')
    (cwd / 'review-conformance.md').write_text('OTHER_AXIS_ONLY\n')
    (cwd / 'secrets').mkdir()
    (cwd / 'secrets/token').write_text('FAKE_ONLY\n')
    (cwd / 'bench/combos').mkdir(parents=True)
    (cwd / 'bench/combos/all-fable.json').write_text('fixture-only\n')
    (cwd / 'linked.txt').symlink_to(external / 'instructions.md')
    (cwd / 'linked-dir').symlink_to(external)
    db = sqlite3.connect(cwd / 'state.sqlite')
    db.execute('pragma journal_mode=wal')
    db.execute('create table runs(id text, status text)')
    db.execute("insert into runs values ('fixture', 'blocked')")
    db.commit()
    logical = list(db.iterdump())
    before = snapshot(cwd)
    assert {'state.sqlite', 'state.sqlite-wal', 'state.sqlite-shm', '.git/index', '.git/HEAD'} <= before.keys()
    assert any(name.startswith('.git/refs/') for name in before)
    spies = external / 'spies'
    spies.mkdir()
    (spies / 'sitecustomize.py').write_text('''import os, sqlite3
from pathlib import Path
log = Path(os.environ['DEVFLOW_TEST_SPY_LOG'])
def forbidden(*args, **kwargs):
    with log.open('a') as stream: stream.write('forbidden connect/transition\\n')
    raise RuntimeError('fixture spy: connect/transition forbidden')
sqlite3.connect = forbidden
from devflow import storage, workflow
storage.connect = forbidden
for name in ('start', 'finish', 'approve', 'interrupt', 'resume'):
    if hasattr(workflow, name): setattr(workflow, name, forbidden)
with log.open('a') as stream: stream.write('spy-ready\\n')
''')
    spy_log = external / 'spy.log'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PI_', 'DEVFLOW_', 'GIT_'))}
    env.update(HOME=str(home), PI_CODING_AGENT_DIR=str(home / '.pi/agent'),
               DEVFLOW_SUBAGENTS_PILOT_PACKAGE=package, DEVFLOW_TEST_FIXTURE=str(cwd),
               DEVFLOW_TEST_EVIDENCE=str(external), DEVFLOW_INSTRUCTIONS=str(instructions),
               DEVFLOW_TEST_BASE=base, DEVFLOW_TEST_HEAD=head,
               DEVFLOW_BROWSER_ENV='DEVFLOW_TEST_ENV_ONLY', DEVFLOW_TEST_SPY_LOG=str(spy_log),
               PYTHONPATH=f'{spies}:{ROOT / "scripts"}',
               PI_SUBAGENTS_PI_CODING_AGENT_PACKAGE_ROOT=str(sdk))
    script = f'''import {{discoverAndLoadExtensions}} from {json.dumps(loader.as_uri())};
const result = await discoverAndLoadExtensions([{json.dumps(str(ROOT / 'tests/pi_subagents_harness.ts'))}],
 {json.dumps(str(external))}, {json.dumps(str(home / '.pi/agent'))});
if(result.errors.length) {{ console.error(JSON.stringify(result.errors)); process.exitCode=1; }}
'''
    try:
        result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=90)
        (external / 'stdout.log').write_text(result.stdout)
        (external / 'stderr.log').write_text(result.stderr)
        after = snapshot(cwd)
        logical_after = list(db.iterdump())
        (external / 'snapshots.json').write_text(json.dumps({'before': before, 'after': after,
                                                           'logical_before': logical, 'logical_after': logical_after}, indent=2))
        assert result.returncode == 0, f'{external}\n{result.stdout}\n{result.stderr}'
        assert before == after, f'Мутация фикстуры: {external}'
        assert logical == logical_after
        spy = spy_log.read_text()
        assert 'spy-ready' in spy and 'forbidden' not in spy
        report = json.loads((external / 'guarded-result.json').read_text())
        report['evidence'] = str(external)
        report['context'] = json.loads((external / 'guarded-context.json').read_text())
        report['snapshots_equal'] = True
        print(f'Guarded evidence: {external}')
        return report
    finally:
        db.close()


@pytest.mark.parametrize('mode', ['target', 'unavailable'])
def test_guarded_foreign_target_through_registered_handlers(mode):
    executable = shutil.which('pi')
    assert executable
    sdk = Path(executable).resolve().parents[2]
    loader = sdk / 'dist/core/extensions/loader.js'
    evidence_root = Path.home() / '.local/state/devflow/pi-subagents-pilot'
    evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    external = Path(tempfile.mkdtemp(prefix='target-probe-', dir=evidence_root))
    cwd = external / 'project'
    home = external / 'home'
    cwd.mkdir()
    (home / '.claude').mkdir(parents=True)
    (home / '.claude/settings.json').write_text('{}')
    (cwd / 'safe.txt').write_text('FIXTURE_ONLY\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PI_', 'DEVFLOW_', 'GIT_'))}
    env.update(HOME=str(home), PI_CODING_AGENT_DIR=str(home / '.pi/agent'),
               DEVFLOW_TEST_TARGET_PROBE=mode, DEVFLOW_TEST_FIXTURE=str(cwd),
               DEVFLOW_TEST_EVIDENCE=str(external))
    script = f'''import {{discoverAndLoadExtensions}} from {json.dumps(loader.as_uri())};
const result = await discoverAndLoadExtensions([{json.dumps(str(ROOT / 'tests/pi_subagents_harness.ts'))}],
 {json.dumps(str(external))}, {json.dumps(str(home / '.pi/agent'))});
if(result.errors.length) {{ console.error(JSON.stringify(result.errors)); process.exitCode=1; }}
'''
    node = shutil.which('node')
    assert node
    if mode == 'unavailable':
        env['PATH'] = '/devflow-test-no-executables'
    result = subprocess.run([node, '--input-type=module', '-e', script], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=30)
    (external / 'stdout.log').write_text(result.stdout)
    (external / 'stderr.log').write_text(result.stderr)
    assert result.returncode == 0, f'{external}\n{result.stdout}\n{result.stderr}'


def test_guarded_fresh_instructions_and_role(guarded):
    body, tools = agent_body('review-standards')
    assert guarded['role']['systemPrompt'] == body
    assert guarded['role']['tools'] == tools
    assert guarded['context']['creates'] == 1
    assert guarded['execCalls'] == 0


def test_guarded_required_extensions_fail_closed(guarded):
    assert guarded['guarded'] is True
    assert guarded['runtimeDisposed'] == 2
    assert guarded['shutdowns'] == 1


def test_guarded_strict_readonly_blocks_before_backend(guarded):
    assert guarded['backendCalls'] == 3
    matrix = guarded['matrix']
    assert all(row['passed'] for row in matrix)
    for ui in (False, True):
        positive = [row for row in matrix if row['hasUI'] == ui and row['kind'] == 'allowed']
        assert {row['verb'] for row in positive} == {'status', 'rev-parse', 'ls-files', 'show', 'diff'}
        assert len(positive) == 5
        denied = [row for row in matrix if row['hasUI'] == ui and row['kind'] == 'denied']
        assert len(denied) >= 60
        for tool, path in [('read', 'guard-denied.txt'), ('grep', 'guard-denied.txt'),
                           ('grep', 'guard-denied-dir'), ('find', 'guard-denied-dir')]:
            assert any(row['verb'] == tool and row['input']['path'] == path for row in denied)


def test_guarded_sdk_cwd_and_environment(guarded):
    assert guarded['context']['envMatches'] is True
    assert guarded['context']['childCwdMatches'] is True


def test_guarded_git_sqlite_and_transition_spies(guarded):
    assert guarded['snapshots_equal'] is True


def test_interactive_no_go_matrix():
    package = os.environ.get('DEVFLOW_SUBAGENTS_PILOT_PACKAGE')
    assert package, 'Нужен явный проверенный пакет'
    executable = shutil.which('pi')
    assert executable
    sdk = Path(executable).resolve().parents[2]
    loader = sdk / 'dist/core/extensions/loader.js'
    evidence_root = Path.home() / '.local/state/devflow/pi-subagents-pilot'
    evidence_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    external = Path(tempfile.mkdtemp(prefix='interactive-matrix-', dir=evidence_root))
    home = external / 'home'
    home.mkdir(mode=0o700)
    secret = 'DEVFLOW_FAKE_SECRET_INTERACTIVE_71e90c'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PI_', 'DEVFLOW_', 'GIT_'))}
    env.update(HOME=str(home), PI_CODING_AGENT_DIR=str(home / '.pi/agent'),
               DEVFLOW_SUBAGENTS_PILOT_PACKAGE=package, DEVFLOW_TEST_INTERACTIVE='1',
               DEVFLOW_TEST_EVIDENCE=str(external), DEVFLOW_BROWSER_ENV=secret)
    script = f'''import {{discoverAndLoadExtensions}} from {json.dumps(loader.as_uri())};
const result = await discoverAndLoadExtensions([{json.dumps(str(ROOT / 'tests/pi_subagents_harness.ts'))}],
 {json.dumps(str(external))}, {json.dumps(str(home / '.pi/agent'))});
if(result.errors.length) {{ console.error(JSON.stringify(result.errors)); process.exitCode=1; }}
'''
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=30)
    (external / 'stdout.log').write_text(result.stdout)
    (external / 'stderr.log').write_text(result.stderr)
    assert result.returncode == 0, f'{external}\n{result.stdout}\n{result.stderr}'
    report = json.loads((external / 'interactive-result.json').read_text())
    assert len(report['rows']) >= 60
    assert all(row['passed'] for row in report['rows'])
    assert report['calls'] == dict(delegation=0, provider=0, child=0, backend=0)
    manifests = list(home.rglob('manifest.json'))
    assert len(manifests) == 8
    for path in manifests:
        data = json.loads(path.read_text())
        assert {'terminalStatus', 'disposeResolved', 'shutdownConfirmed',
                'noActiveWorkConfirmed', 'outcome'} <= data.keys()
        assert data['realModelSession'] is False
        assert data['shutdownConfirmed'] == 'unknown'
        assert data['noActiveWorkConfirmed'] == 'unknown'
        assert data['outcome'] == 'unavailable'
        assert path.with_name('report.md').is_file()
    factory = json.loads((external / 'factory-result.json').read_text())
    assert factory == dict(disposeResolved=True, shutdownFinished=False, errors=[],
                           syntheticTerminal='completed', realModelSession=False, outcome='unavailable')
    for path in external.rglob('*'):
        if path.is_file():
            assert secret.encode() not in path.read_bytes(), str(path)
    print(f'Interactive evidence (NO-GO, не реальное ревью): {external}')
