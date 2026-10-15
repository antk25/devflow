"""The two benchmark executors as processes: probe calls and the parsing of what claude and pi print."""
import json
import re
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from .documents import WorkflowError, document
from .pi import agent_body, build_command
from .policy import PHASES

RUNNERS = ('claude', 'pi')
PROBE_MESSAGE = 'Reply with the single word: ok'
PROBE_TIMEOUT = 180
AGENTS = Path(__file__).resolve().parents[2] / 'agents'


def host_execute(cmd, timeout):
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)


# Host-side isolation of claude: no user settings (hooks, deny rules, agents), no MCP, no skills, no web tools.
# `--disallowedTools` is variadic, so the message goes right after `-p`.
CLAUDE_ISOLATION = ['--setting-sources', 'project', '--strict-mcp-config', '--disable-slash-commands',
                    '--disallowedTools', 'WebFetch,WebSearch']
WEB_TOOLS = ('WebFetch', 'WebSearch')
# Host-side isolation of pi, the counterpart of CLAUDE_ISOLATION: no extensions (their tools and hooks), no AGENTS.md
# auto-loading (claude does not load it either); the tool allowlist comes from the agent frontmatter.
PI_ISOLATION = ['--no-extensions', '--no-context-files']


def claude_probe_command(model, effort, output_format='json'):
    return ['claude', '-p', PROBE_MESSAGE, '--model', model, '--effort', effort, '--output-format', output_format,
            '--no-session-persistence', '--max-turns', '1', *CLAUDE_ISOLATION]


def claude_init(stdout):
    """The `system/init` record of a `--output-format stream-json --verbose` reply; None when there is none."""
    for line in stdout.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get('type') == 'system' and record.get('subtype') == 'init':
            return record
    return None


def pi_probe_command(model, effort, session_dir):
    return ['pi', '-p', *PI_ISOLATION, '--session-dir', str(session_dir),
            '--model', f'{model}:{effort}', PROBE_MESSAGE]


def claude_result(stdout):
    """The JSON object of a `claude -p --output-format json` reply; None when stdout holds none."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def pi_records(session_dir):
    records = []
    for path in sorted(Path(session_dir).rglob('*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def pi_assistant_messages(session_dir):
    messages = []
    for record in pi_records(session_dir):
        message = record.get('message') if record.get('type') == 'message' else None
        if isinstance(message, dict) and message.get('role') == 'assistant':
            messages.append(message)
    return messages


def probe(execute, runner, model, effort):
    """One short call; `{ok, model_actual, error_text}`. Errors come from the reply, not the exit code."""
    if runner not in RUNNERS:
        return {'ok': False, 'model_actual': None, 'error_text': f'unknown runner: {runner}'}
    try:
        if runner == 'claude':
            proc = execute(claude_probe_command(model, effort), PROBE_TIMEOUT)
            data = claude_result(proc.stdout)
            if data is None:
                return {'ok': False, 'model_actual': None,
                        'error_text': (proc.stderr or proc.stdout or f'exit {proc.returncode}').strip()}
            used = list(data.get('modelUsage') or {})
            if data.get('is_error') or proc.returncode:
                return {'ok': False, 'model_actual': used[0] if used else None,
                        'error_text': str(data.get('result') or data.get('subtype') or proc.stderr).strip()}
            return {'ok': True, 'model_actual': used[0] if used else None, 'error_text': None}
        with tempfile.TemporaryDirectory(prefix='devflow-bench-probe-') as session_dir:
            proc = execute(pi_probe_command(model, effort, session_dir), PROBE_TIMEOUT)
            messages = pi_assistant_messages(session_dir)
        if not messages:
            return {'ok': False, 'model_actual': None,
                    'error_text': (proc.stderr or proc.stdout or 'pi wrote no assistant message').strip()}
        last = messages[-1]
        actual = f"{last.get('provider')}/{last.get('model')}" if last.get('model') else None
        if last.get('stopReason') == 'error' or proc.returncode:
            return {'ok': False, 'model_actual': actual,
                    'error_text': str(last.get('errorMessage') or proc.stderr).strip()}
        return {'ok': True, 'model_actual': actual, 'error_text': None}
    except subprocess.TimeoutExpired:
        return {'ok': False, 'model_actual': None, 'error_text': f'timeout after {PROBE_TIMEOUT}s'}
    except OSError as exc:
        return {'ok': False, 'model_actual': None, 'error_text': str(exc)}


def claude_agent(phase):
    """Inline `--agents` definition of a phase agent: with `--setting-sources project` the user's agents are not loaded."""
    path = AGENTS / f'{phase}.md'
    if phase not in PHASES or not path.is_file():
        raise WorkflowError(f'Unknown phase: {phase}')
    doc = document(path)
    tools = [t.strip() for t in str(doc['meta'].get('tools', '')).split(',') if t.strip()]
    return {phase: {'description': str(doc['meta'].get('description', phase)), 'prompt': doc['body'].strip() + '\n',
                    'tools': tools}}


def claude_command(phase, spec, session_id, message, budget, agents_file):
    cmd = ['claude', '-p', message, '--agents', str(agents_file), '--agent', phase, '--model', spec['model'],
           '--effort', spec['effort'], '--session-id', session_id, '--output-format', 'json',
           '--permission-mode', 'bypassPermissions']
    if budget is not None:
        cmd += ['--max-budget-usd', str(budget)]
    return cmd + CLAUDE_ISOLATION


def transcript_paths(home, cwd, session_id):
    """The session transcript under `<home>/.claude/projects/<cwd slug>/` plus its subagent transcripts."""
    project = Path(home) / '.claude/projects' / re.sub(r'[^A-Za-z0-9]', '-', str(cwd))
    paths = [project / f'{session_id}.jsonl']
    paths += sorted((project / session_id).rglob('*.jsonl'))
    return [p for p in paths if p.is_file()]


def transcript_facts(paths):
    """Effort levels, tool-call counts and models of the assistant records of the transcripts."""
    efforts, tools, models = [], {}, []
    for path in paths:
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get('type') != 'assistant':
                continue
            effort = record.get('effort')
            if effort and effort not in efforts:
                efforts.append(effort)
            message = record.get('message') or {}
            if message.get('model') and message['model'] not in models:
                models.append(message['model'])
            for block in message.get('content') or []:
                if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('name'):
                    tools[block['name']] = tools.get(block['name'], 0) + 1
    return {'efforts': efforts, 'tools': tools, 'models': models}


def claude_metrics(stdout, home, cwd, session_id=None):
    """One phase record from a `claude -p --output-format json` reply and the session transcript."""
    data = claude_result(stdout) or {}
    usage = data.get('modelUsage') or {}
    totals = {'input': 0, 'output': 0, 'reasoning': 0, 'cache_read': 0, 'cache_write': 0}
    for item in usage.values():
        totals['input'] += int(item.get('inputTokens') or 0)
        totals['output'] += int(item.get('outputTokens') or 0)
        totals['reasoning'] += int(item.get('thinkingTokens') or 0)
        totals['cache_read'] += int(item.get('cacheReadInputTokens') or 0)
        totals['cache_write'] += int(item.get('cacheCreationInputTokens') or 0)
    dominant = max(usage, key=lambda m: float(usage[m].get('costUSD') or 0), default=None)
    session_id = session_id or data.get('session_id')
    facts = transcript_facts(transcript_paths(home, cwd, session_id)) if session_id else transcript_facts([])
    return {'runner': 'claude', 'model_actual': dominant, 'models': sorted(usage) or facts['models'],
            'effort_actual': ','.join(facts['efforts']) or None, **totals,
            'cost_usd': float(data.get('total_cost_usd') or 0), 'cost_source': 'anthropic-list',
            'duration_s': round(float(data.get('duration_ms') or 0) / 1000, 1), 'turns': int(data.get('num_turns') or 0),
            'tools': facts['tools'], 'session_id': session_id,
            'is_error': bool(data.get('is_error')), 'subtype': data.get('subtype'), 'result': data.get('result')}


def claude_error(data, proc):
    """`(error, error_text)` of a claude reply: budget stop, API error, or none."""
    if data is None:
        return 'api', (proc.stderr or proc.stdout or f'exit {proc.returncode}').strip()[-500:]
    subtype = str(data.get('subtype') or '')
    if 'budget' in subtype:
        return 'budget', str(data.get('result') or subtype)[-500:]
    if data.get('is_error') or proc.returncode:
        return 'api', str(data.get('result') or subtype or proc.stderr).strip()[-500:]
    return None, None


def pi_command(phase, spec, session_dir, session_id, message, sb):
    """pi argv of a phase: the agent body in a file under the sandbox (visible in the container), a session directory
    of its own so that the metrics of one phase never include another's."""
    body, tools = agent_body(phase)
    body_file = Path(sb['dir']) / f'pi-agent-{phase}.md'
    body_file.write_text(body, encoding='utf-8')
    options = [*PI_ISOLATION, '--session-dir', str(session_dir), '--session-id', session_id]
    return build_command(body_file, tools, f"{spec['model']}:{spec['effort']}", message, options)


def pi_metrics(session_dir, duration_s):
    """One phase record from the pi session: usage summed over assistant replies, cost from pi's catalog."""
    records = pi_records(session_dir)
    messages = [r['message'] for r in records if r.get('type') == 'message'
                and isinstance(r.get('message'), dict) and r['message'].get('role') == 'assistant']
    totals = {'input': 0, 'output': 0, 'reasoning': 0, 'cache_read': 0, 'cache_write': 0}
    cost, tools, models, efforts = 0.0, {}, [], []
    for message in messages:
        usage = message.get('usage') or {}
        totals['input'] += int(usage.get('input') or 0)
        totals['output'] += int(usage.get('output') or 0)
        totals['reasoning'] += int(usage.get('reasoning') or 0)
        totals['cache_read'] += int(usage.get('cacheRead') or 0)
        totals['cache_write'] += int(usage.get('cacheWrite') or 0)
        cost += float((usage.get('cost') or {}).get('total') or 0)
        if message.get('model'):
            name = f"{message.get('provider')}/{message['model']}"
            if name not in models:
                models.append(name)
        for block in message.get('content') or []:
            if isinstance(block, dict) and block.get('type') == 'toolCall' and block.get('name'):
                tools[block['name']] = tools.get(block['name'], 0) + 1
    for record in records:
        level = record.get('thinkingLevel') if record.get('type') == 'thinking_level_change' else None
        if level and level not in efforts:
            efforts.append(level)
    last = messages[-1] if messages else {}
    return {'runner': 'pi', 'model_actual': models[-1] if models else None, 'models': models,
            'effort_actual': ','.join(efforts) or None, **totals, 'cost_usd': round(cost, 6), 'cost_source': 'pi-catalog',
            'duration_s': round(float(duration_s), 1), 'turns': len(messages), 'tools': tools, 'session_id': None,
            'is_error': last.get('stopReason') == 'error', 'subtype': last.get('stopReason'), 'result': None}


def pi_error(metrics, messages, proc):
    """`(error, error_text)` of a pi phase: `stopReason: error` is an API error whatever the exit code."""
    if not messages:
        return 'api', (proc.stderr or proc.stdout or 'pi wrote no assistant message').strip()[-500:]
    last = messages[-1]
    if metrics['is_error'] or proc.returncode:
        return 'api', str(last.get('errorMessage') or proc.stderr or f'exit {proc.returncode}').strip()[-500:]
    return None, None


def run_pi_phase(execute, phase, spec, message, sb, timeout):
    session_id = str(uuid.uuid4())
    session_dir = Path(sb['home']) / 'pi-sessions' / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    cmd = pi_command(phase, spec, session_dir, session_id, message, sb)
    started = time.monotonic()
    try:
        proc = execute(cmd, timeout)
    except subprocess.TimeoutExpired:
        metrics = pi_metrics(session_dir, timeout)
        metrics['session_id'] = session_id
        return {'metrics': metrics, 'report': '', 'error': 'timeout', 'error_text': f'timeout after {timeout}s'}
    metrics = pi_metrics(session_dir, time.monotonic() - started)
    metrics['session_id'] = session_id
    error, error_text = pi_error(metrics, pi_assistant_messages(session_dir), proc)
    return {'metrics': metrics, 'report': proc.stdout, 'error': error, 'error_text': error_text}


def run_phase(execute, runner, phase, spec, message, sb, timeout, budget, home=None):
    """One phase by one runner: `{metrics, report, error: None|'api'|'budget'|'timeout', error_text}`."""
    if runner not in RUNNERS:
        raise WorkflowError(f'unknown runner: {runner}')
    if runner == 'pi':
        return run_pi_phase(execute, phase, spec, message, sb, timeout)
    home = Path(home or Path.home())
    session_id = str(uuid.uuid4())
    agents_file = Path(sb['home']) / f'agents-{phase}.json'
    agents_file.write_text(json.dumps(claude_agent(phase), ensure_ascii=False), encoding='utf-8')
    try:
        proc = execute(claude_command(phase, spec, session_id, message, budget, agents_file), timeout)
    except subprocess.TimeoutExpired:
        metrics = claude_metrics('', home, sb['repo'], session_id)
        metrics['duration_s'] = float(timeout)
        return {'metrics': metrics, 'report': '', 'error': 'timeout', 'error_text': f'timeout after {timeout}s'}
    data = claude_result(proc.stdout)
    metrics = claude_metrics(proc.stdout, home, sb['repo'], session_id)
    error, error_text = claude_error(data, proc)
    return {'metrics': metrics, 'report': str(data.get('result') or '') if data else proc.stdout, 'error': error,
            'error_text': error_text}
