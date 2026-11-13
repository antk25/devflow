"""Everything DevFlow knows about pi as a process: system-prompt addition, model selection, phase runs.

Model for a phase run: `--model` > policy (`route.launch.pi.model`) > `PI_*` env > pi default."""
import json
import os
import re
import signal
import time
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import harness_claude, harness_codex, harness_pi, transcripts
from .documents import WorkflowError, artifact, document
from .harness_pi import build_command
from .policy import launch as launch_for
from .policy import PHASES, limits_path, load, policy_path, resolve_pi_role
from .storage import record_outcome
from .workflow import interrupt, route, start

PI_SETTINGS = Path.home() / '.pi/agent/settings.json'
AGENTS = Path(__file__).resolve().parents[2] / 'agents'
ROLES = ('crossreview', 'second-opinion', 'review-standards', 'review-conformance', 'reader', 'browser')
INACTIVE = ('needs_init', 'invalid', 'migration_required', 'completed')
PRECONDITIONS = {'research': ('research',), 'plan': ('plan', 'plan_outdated'), 'implement': ('ready',)}
RUNNING_WARNING = ('phase did not record finish; run is still running — inspect git status and the changelog, then '
                   'devflow finish/resume/interrupt; do not run phase run implement again')
HARNESSES = {'pi': harness_pi, 'claude': harness_claude, 'codex': harness_codex}
PHASE_TIMEOUT = 5400
REQUIRED_SECTIONS = {'research': ('## Problem', '## Recommendation'), 'plan': ('## Steps',), 'implement': ()}
LIMITS_STALE = 'limits stale'
TOOLS = {'Read': ('read',), 'Grep': ('grep',), 'Glob': ('find', 'ls'), 'Bash': ('bash',),
         'Write': ('write',), 'Edit': ('edit',)}
CODEX_WARNING = 'Модели openai-codex в pi не запускаются — только в Codex'
PHASE_NOT_IN_PI = 'Фаза {} в pi не запускается по model-policy: research/plan — в Claude Code, при исчерпанных лимитах — в Codex'
BRIDGE_WARNING = ('claude-bridge запрещён в pi; выберите --model provider/id или прямой anthropic/*')
SHARED_INSTRUCTIONS = Path.home() / '.claude/devflow-instructions.md'
EXTENSION = Path(__file__).resolve().parents[2] / 'pi/extensions/devflow.ts'


def shared_instructions(path):
    try:
        text = Path(path).read_text(encoding='utf-8').strip()
        if not text:
            raise ValueError('пустой файл')
        return text
    except (OSError, ValueError) as exc:
        raise WorkflowError(f'Общие инструкции недоступны: {path}: {exc}; запустите ./install.sh')


def ensure_pi_model(model, settings_path):
    if model:
        provider, separator, model_id = model.partition('/')
        if not separator or not model_id or any(c in provider for c in '*?[]'):
            raise WorkflowError('Укажите точную модель pi как provider/id[:thinking], без шаблона провайдера')
    else:
        path = Path(settings_path)
        try:
            settings = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(settings, dict):
                raise ValueError('expected an object')
            provider = settings.get('defaultProvider')
        except FileNotFoundError:
            provider = None
        except (OSError, ValueError) as exc:
            raise WorkflowError(f'Cannot read pi settings {path}: {exc}')
    if isinstance(provider, str) and provider.lower() == 'claude-bridge':
        raise WorkflowError(BRIDGE_WARNING)
    if isinstance(provider, str) and provider.lower() == 'openai-codex':
        raise WorkflowError(CODEX_WARNING)


def settings_path(env):
    return Path(env['PI_CODING_AGENT_DIR']) / 'settings.json' if env.get('PI_CODING_AGENT_DIR') else PI_SETTINGS


def extension_path(env):
    installed = Path(env.get('PI_CODING_AGENT_DIR', Path.home() / '.pi/agent')) / 'extensions/devflow.ts'
    if installed.exists():
        if installed.resolve() != EXTENSION.resolve():
            raise WorkflowError(f'CONFLICT pi extension: {installed}; запустите ./install.sh')
        # pi deduplicates paths, not symlink targets: use the discovery path, not the source path.
        return installed
    return EXTENSION


def task_key(active):
    """Jira key (slug prefix) of the most advanced active task, or None."""
    for folder in ('plans', 'research', 'tz'):
        for item in active.get(folder, ()):
            if item.get('status') in INACTIVE:
                continue
            m = re.match(r'([a-z]+-\d+)', item['name'].lower())
            if m:
                return m[1].upper()
    return None


def task_slug(active):
    names = {item['name'].lower() for folder in ('plans', 'research', 'tz')
             for item in active.get(folder, ()) if item.get('status') not in ('invalid', 'completed', 'archived', 'closed')}
    if len(names) > 1:
        raise WorkflowError('Неоднозначная задача; укажите полный slug: ' + ', '.join(sorted(names)))
    return next(iter(names), None)


def preamble(ctx, active, handoff):
    parts = ['PROJECT_RESTORE', json.dumps({k: str(v) for k, v in ctx.items()}, ensure_ascii=False, indent=2),
             'OBSIDIAN_CONTEXT', json.dumps(active, ensure_ascii=False, indent=2)]
    if handoff:
        parts += [f"HANDOFF {handoff['path']}", handoff['body'].strip(),
                  'После чтения передачи выполните devflow route <полный slug>. '
                  'Передача не разрешает автоматические approve/finish/resume; recovery требует явного решения.']
    return '\n'.join(parts) + '\n'


def model_arg(env, override=None):
    if override:
        return override
    provider, model = env.get('PI_PROVIDER'), env.get('PI_MODEL')
    if not provider or not model:
        return None
    level = env.get('PI_REASONING_LEVEL')
    return f'{provider}/{model}' + (f':{level}' if level else '')


def model_env(model):
    """PI_* variables for `provider/id[:level]`, so phase processes inherit the session's model."""
    provider, _, rest = model.partition('/')
    if not provider or not rest:
        return {}
    model_id, _, level = rest.partition(':')
    env = {'PI_PROVIDER': provider, 'PI_MODEL': model_id}
    if level:
        env['PI_REASONING_LEVEL'] = level
    return env


def warns_claude_bridge(model_arg, settings_path=PI_SETTINGS):
    if model_arg:
        return model_arg.startswith('claude-bridge/')
    try:
        return json.loads(Path(settings_path).read_text(encoding='utf-8')).get('defaultProvider') == 'claude-bridge'
    except (OSError, ValueError, AttributeError):
        return False


def agent_body(phase):
    path = AGENTS / f'{phase}.md'
    if phase not in (*PHASES, *ROLES) or not path.is_file():
        raise WorkflowError(f'Unknown phase: {phase}')
    doc = document(path)
    tools = []
    for name in str(doc['meta'].get('tools', '')).split(','):
        for tool in TOOLS.get(name.strip(), ()):
            if tool not in tools:
                tools.append(tool)
    return doc['body'].strip() + '\n', tools


def task_message(phase, ctx, state, step=None, run=None, note=None):
    lines = [f'DevFlow Phase — {phase}.', '', f"cwd: {ctx['cwd']}", f"slug: {state['slug']}",
             f"vault: {ctx['vault']}"]
    for key in ('research_revision', 'plan_revision', 'research_path', 'plan_path'):
        if state.get(key):
            lines.append(f"{key}: {state[key]}")
    tz = artifact(ctx['vault'], 'tz', state['slug'])
    if tz:
        lines.append(f"tz: {tz['path']}")
    if run:
        lines += ['', f"run_id: {run['run_id']}", f"step: {run['step']}" + (f" (n={state['n']})" if state.get('n') else ''),
                  f"plan_revision: {run['revision']}"]
    if note:
        lines += ['', 'Замечание пользователя:', note.strip()]
    return '\n'.join(lines) + '\n'


def _cleanup_process_group(child, grace=2.0):
    try:
        try:
            os.killpg(child.pid, signal.SIGTERM)
            deadline = time.monotonic() + grace
            while True:
                os.killpg(child.pid, 0)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    os.killpg(child.pid, signal.SIGKILL)
                    break
                time.sleep(min(0.05, remaining))
        except ProcessLookupError:
            pass
    finally:
        child.wait(timeout=max(0.1, grace))


def _browser_process(command, ctx, message, env, timeout):
    match = re.search(r'^Аргументы: (.+)$', message, re.M)
    slug = re.search(r'(?:^|;)\s*slug: ([a-z0-9-]+)\s*(?:;|$)', match[1]) if match else None
    if not slug:
        raise WorkflowError('browser requires Аргументы: with slug: <slug>;')
    slug = slug[1]
    verdict = Path('/tmp/devflow-smoke') / slug / 'verdict.md'
    if f'Вердикт: {verdict}' not in message.splitlines():
        raise WorkflowError(f'browser requires Вердикт: {verdict}')
    verdict = Path(env.get('DEVFLOW_SMOKE_DIR', '/tmp/devflow-smoke')) / slug / 'verdict.md'
    wrappers = Path(__file__).resolve().parents[2] / 'bin'
    wait_command = [str(wrappers / 'devflow-smoke-wait')]
    prep = subprocess.run([*wait_command, 'prep', slug], env=env, capture_output=True, text=True)
    if prep.returncode:
        return prep
    proc = waiter = None
    deadline = time.monotonic() + min(timeout or 420, 420)
    with tempfile.TemporaryFile(mode='w+') as out, tempfile.TemporaryFile(mode='w+') as err, \
            tempfile.TemporaryFile(mode='w+') as wait_out, tempfile.TemporaryFile(mode='w+') as wait_err:
        code = None
        cleanup_errors = []
        cleanup_failed = False
        try:
            proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, cwd=ctx['cwd'], env=env,
                                    stdout=out, stderr=err, start_new_session=True)
            waiter = subprocess.Popen([*wait_command, 'wait', slug], env=env,
                                      stdout=wait_out, stderr=wait_err, start_new_session=True)
            while proc.poll() is None:
                if waiter.poll() not in (None, 0):
                    code = waiter.returncode
                    break
                if time.monotonic() >= deadline:
                    code = 124
                    break
                try:
                    proc.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            if code is None:
                code = proc.returncode
                if code == 0:
                    if not verdict.is_file() or not verdict.stat().st_size:
                        code = 1
                    else:
                        checked = subprocess.run([*wait_command, 'wait', slug], env=env,
                                                 capture_output=True, text=True,
                                                 timeout=max(0.1, deadline - time.monotonic()))
                        code = checked.returncode
        except subprocess.TimeoutExpired:
            code = 124
        finally:
            for child in (proc, waiter):
                if child is not None:
                    try:
                        _cleanup_process_group(child)
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        cleanup_errors.append(str(exc))
                        cleanup_failed = True
            try:
                cleanup = subprocess.run([str(wrappers / 'devflow-browser'), 'stop-task', slug],
                                         env=env, capture_output=True, text=True, timeout=30)
                if cleanup.returncode:
                    code = cleanup.returncode
                cleanup_errors.append(cleanup.stderr)
            except (OSError, subprocess.TimeoutExpired) as exc:
                cleanup_errors.append(str(exc))
                code = 1
            if cleanup_failed:
                code = code or 1
            if code is None or code:
                verdict.unlink(missing_ok=True)
        out.seek(0); err.seek(0); wait_err.seek(0)
        report, errors = out.read(), err.read() + wait_err.read() + '\n'.join(cleanup_errors)
        if code:
            verdict.unlink(missing_ok=True)
        return subprocess.CompletedProcess(command, code, report, errors)


def _run_process(ctx, name, body, tools, chosen, message, env, timeout=None):
    extension = extension_path(env)
    with tempfile.NamedTemporaryFile('w', suffix='.md', prefix='devflow-' + name + '-', delete=False,
                                     encoding='utf-8') as fh:
        fh.write(body)
    body_file = Path(fh.name)
    try:
        command = build_command(body_file, tools, chosen, message,
                                options=('--no-session', '--extension', str(extension)))
        if name == 'browser' and re.search(r'^Вердикт:', message, re.M):
            return _browser_process(command, ctx, message, env, timeout)
        deadline = None if timeout is None else time.monotonic() + timeout
        with tempfile.TemporaryFile(mode='w+') as out, tempfile.TemporaryFile(mode='w+') as err:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, cwd=ctx['cwd'], env=env,
                                     stdout=out, stderr=err, start_new_session=True)
            expired = False
            try:
                child.wait(timeout=None if deadline is None else max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                expired = True
            finally:
                _cleanup_process_group(child)
            out.seek(0); err.seek(0)
            report, errors = out.read(), err.read()
            if expired:
                raise subprocess.TimeoutExpired(command, timeout, output=report, stderr=errors)
            return subprocess.CompletedProcess(command, child.returncode, report, errors)
    finally:
        body_file.unlink(missing_ok=True)


def run_agent(ctx, role, message, model=None, env=None, timeout=600):
    if role not in ROLES:
        raise WorkflowError(f'Unknown role: {role}')
    if timeout <= 0:
        raise WorkflowError('--timeout must be positive')
    env = dict(os.environ if env is None else env)
    body, tools = agent_body(role)
    selection = resolve_pi_role(load(Path(env.get('DEVFLOW_MODEL_POLICY', policy_path()))), role, env, model)
    chosen = selection['model']
    ensure_pi_model(chosen, settings_path(env))
    shared_instructions(Path(env.get('DEVFLOW_INSTRUCTIONS', SHARED_INSTRUCTIONS)))
    if not shutil.which('pi', path=env.get('PATH')):
        raise WorkflowError('pi CLI is missing from PATH')
    result = {'role': role, 'host': 'pi', **selection, 'session_id': None, 'session_path': None}
    if selection['model_source'] in ('inherited', 'default'):
        result['model_note'] = 'Модель роли наследуется; независимость обеспечена отдельным контекстом'
    executor = chosen
    if not executor:
        try:
            settings = json.loads(settings_path(env).read_text())
            if settings.get('defaultProvider') and settings.get('defaultModel'):
                executor = settings['defaultProvider'] + '/' + settings['defaultModel']
        except FileNotFoundError:
            pass
    provenance = f'Исполнитель: host=pi model={executor or "pi default (неизвестна)"}\n'
    try:
        proc = _run_process(ctx, role, body, tools, chosen, provenance + message, env, timeout)
        result.update(exit_code=proc.returncode, report=proc.stdout, stderr=proc.stderr)
        if proc.returncode != 0 or not proc.stdout.strip():
            result['warning'] = 'Обзор не завершён: ошибка процесса или пустой ответ'
    except subprocess.TimeoutExpired as exc:
        def text(value):
            return value.decode(errors='replace') if isinstance(value, bytes) else value or ''
        result.update(exit_code=124, report=text(exc.stdout), stderr=text(exc.stderr), warning='Обзор не завершён: timeout')
    except OSError as exc:
        raise WorkflowError(f'pi failed to launch: {exc}')
    result['executor'] = executor
    return result


def check_artifact(path, started_at, required_sections):
    """'ok' when the file was written by this run and has every required section, else the reason."""
    if not path or not Path(path).is_file():
        return 'артефакт не найден'
    path = Path(path)
    if path.stat().st_mtime < started_at:
        return f'артефакт не изменён этим запуском: {path}'
    text = path.read_text(encoding='utf-8')
    lines = {line.rstrip() for line in text.splitlines()}
    missing = [s for s in required_sections if s not in lines and not s.startswith('<!--')]
    missing += [s for s in required_sections if s.startswith('<!--') and s not in text]
    return 'нет разделов: ' + ', '.join(missing) if missing else 'ok'


def phase_artifact(ctx, slug, phase, run=None):
    if phase == 'implement':
        found = sorted(Path(ctx['vault'], 'changelog').glob(f'*-{slug}.md'))
        return (found[0] if len(found) == 1 else None), (f"<!-- devflow-run: {run['run_id']} -->",) if run else ()
    folder = Path(ctx['vault'], 'research' if phase == 'research' else 'plans')
    found = [p for p in folder.glob('*.md') if p.stem.lower() == slug.lower()]
    return (found[0] if len(found) == 1 else folder / f'{slug}.md'), REQUIRED_SECTIONS[phase]


def _pi_launch(ctx, phase, current, model, env):
    body, tools = agent_body(phase)
    policy = load(policy_path())
    spec = (current.get('launch') or {}).get('claude') or {}
    if policy and phase not in policy['pi']:
        if (current.get('launch') or {}).get('harness') != 'pi':
            raise WorkflowError(PHASE_NOT_IN_PI.format(phase))
        from_policy = spec['id'] + (':' + spec['effort'] if spec.get('effort') else '')
    else:
        from_policy = (current.get('launch', {}).get('pi') or {}).get('model')
    chosen = model_arg(env, model or from_policy)
    source = 'override' if model else 'policy' if from_policy else 'env' if chosen else 'default'
    ensure_pi_model(chosen, settings_path(env))
    shared_instructions(Path(env.get('DEVFLOW_INSTRUCTIONS', SHARED_INSTRUCTIONS)))
    extension_path(env)
    return chosen, source, lambda message: _run_process(ctx, phase, body, tools, chosen, message, env)


def _run_bounded(argv, ctx, env):
    timeout = int(env.get('DEVFLOW_PHASE_TIMEOUT') or PHASE_TIMEOUT)
    with tempfile.TemporaryFile(mode='w+') as out, tempfile.TemporaryFile(mode='w+') as err:
        # The restore hook must not hand a phase child the interactive session's handoff.
        env = {**env, 'DEVFLOW_PHASE_CHILD': '1'}
        child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, cwd=ctx['cwd'], env=env,
                                 stdout=out, stderr=err, start_new_session=True)
        expired = False
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            expired = True
        finally:
            _cleanup_process_group(child)
        out.seek(0); err.seek(0)
        report, errors = out.read(), err.read()
    if expired:
        return subprocess.CompletedProcess(argv, 124, report, errors + f'\nphase run: timeout {timeout}s\n')
    return subprocess.CompletedProcess(argv, child.returncode, report, errors)


def _claude_launch(ctx, phase, current, model, env):
    spec = (current.get('launch') or {}).get('claude') or {}
    chosen = model or spec.get('id') or spec.get('model')
    if not chosen:
        raise WorkflowError('Модель claude не задана: нет model-policy и --model')
    tools = [t.strip() for t in str(document(AGENTS / f'{phase}.md')['meta'].get('tools', '')).split(',') if t.strip()]

    def launch(message):
        argv = harness_claude.build_command(spec.get('agent') or phase, chosen, spec.get('effort'), tools, message,
                                            add_dirs=(ctx['vault'],))
        return _run_bounded(argv, ctx, env)
    return chosen, 'override' if model else 'policy', launch


def _codex_launch(ctx, phase, current, model, env):
    launch_spec = current.get('launch') or {}
    spec, from_policy = launch_spec.get('claude') or {}, None
    if launch_spec.get('harness') == 'codex':
        from_policy = spec.get('id')
    elif (launch_spec.get('pi') or {}).get('harness') == 'codex':
        from_policy, _, effort = launch_spec['pi']['model'].partition(':')
        spec = {'id': from_policy, 'effort': effort or None}
    chosen = model or from_policy
    if not chosen:
        raise WorkflowError('Модель codex не задана: в policy нет строки harness: codex и нет --model')
    body, _ = agent_body(phase)

    def launch(message):
        argv = harness_codex.build_command(chosen, spec.get('effort') if from_policy else None,
                                           harness_codex.prompt(body, message), ctx['cwd'], add_dirs=(ctx['vault'],))
        return _run_bounded(argv, ctx, env)
    return chosen, 'override' if model else 'policy', launch


def run_phase(ctx, db, slug, phase, step=None, note=None, model=None, env=None, replan=False, host=None):
    env = dict(os.environ if env is None else env)
    current = route(ctx, db, slug)
    if current.get('phase') not in (None, phase) and current.get('policy'):
        current = {**current, **launch_for(phase, (current.get('complexity') or {}).get('value'))}
    host = host or ((current.get('launch') or {}).get('pi') or {}).get('harness') or 'pi'
    if host not in HARNESSES:
        raise WorkflowError(f'Харнес {host} не подключён к phase run; доступны: ' + ', '.join(HARNESSES))
    harness = HARNESSES[host]
    at_own_gate = current['state'] == 'approval_required' and current.get('phase') == phase
    if replan and (phase, current['state']) not in (('plan', 'ready'), ('research', 'completed'), ('research', 'crossreview_required')):
        raise WorkflowError('--replan requires phase plan in state ready or phase research in state completed or crossreview_required')
    if current['state'] not in PRECONDITIONS.get(phase, ()) and not at_own_gate and not replan:
        raise WorkflowError(f"Phase {phase} cannot run from state {current['state']}")
    if not shutil.which(host, path=env.get('PATH')):
        raise WorkflowError(f'{host} CLI is missing from PATH')
    if host == 'claude':
        chosen, source, launch = _claude_launch(ctx, phase, current, model, env)
    elif host == 'codex':
        chosen, source, launch = _codex_launch(ctx, phase, current, model, env)
    else:
        chosen, source, launch = _pi_launch(ctx, phase, current, model, env)
    complexity = (current.get('complexity') or {}).get('value')
    run = None
    if phase == 'implement':
        step = step or current['step']
        if step not in current['frontier']:
            raise WorkflowError(f'Step {step} is not on the frontier: ' + ', '.join(current['frontier']))
        run = start(ctx, db, current['slug'], step, current['revision'])
        if step != current['step']:
            current = dict(current, n=None)

    def outcome(status, parsed):
        record_outcome(db, current['slug'], phase, host, chosen, complexity, status,
                       parsed.get('tokens'), parsed.get('cost'), run and run['run_id'])

    started_at = time.time() - 1
    try:
        proc = launch(task_message(phase, ctx, current, step, run, note))
    except OSError as exc:
        outcome('failed', {})
        if run:
            interrupt(db, run['run_id'], f'{host} failed to launch: {exc}')
        raise WorkflowError(f'{host} failed to launch: {exc}')
    parsed = harness.parse(proc.stdout, proc.stderr, proc.returncode)
    path, sections = phase_artifact(ctx, current['slug'], phase, run)
    check = check_artifact(path, started_at, sections)
    status = 'ok' if parsed['status'] == 'ok' and check == 'ok' else 'failed'
    outcome(status, parsed)
    if host == 'claude' and parsed.get('session_id'):
        transcripts.mark_session(parsed['session_id'], current['slug'], phase=phase)
    after = route(ctx, db, current['slug'])
    result = {'phase': phase, 'slug': current['slug'], 'host': host, 'status': status,
              'artifact': str(path) if path else None, 'tokens': parsed['tokens'], 'cost': parsed['cost'],
              'session_id': parsed['session_id'], 'model': chosen, 'model_source': source,
              'exit_code': proc.returncode, 'report': parsed.get('report', proc.stdout), 'stderr': proc.stderr, 'route': after}
    if status == 'failed':
        result['reason'] = check if check != 'ok' else 'ошибка процесса или пустой ответ'
    warnings = []
    if run:
        result['run_id'] = run['run_id']
        if after['state'] == 'running':
            warnings.append(RUNNING_WARNING)
    if current.get('policy') and current.get('limits') is None and limits_path().is_file():
        warnings.append(LIMITS_STALE)
    if warnings:
        result['warning'] = '; '.join(warnings)
    return result
