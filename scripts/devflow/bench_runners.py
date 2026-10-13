"""The two benchmark executors as processes: probe calls and the parsing of what claude and pi print."""
import json
import subprocess
import tempfile
from pathlib import Path

RUNNERS = ('claude', 'pi')
PROBE_MESSAGE = 'Reply with the single word: ok'
PROBE_TIMEOUT = 180


def host_execute(cmd, timeout):
    return subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)


# Host-side isolation of claude: no user settings (hooks, deny rules, agents), no MCP, no skills, no web tools.
# `--disallowedTools` is variadic, so the message goes right after `-p`.
CLAUDE_ISOLATION = ['--setting-sources', 'project', '--strict-mcp-config', '--disable-slash-commands',
                    '--disallowedTools', 'WebFetch,WebSearch']
WEB_TOOLS = ('WebFetch', 'WebSearch')


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
    return ['pi', '-p', '--no-extensions', '--no-context-files', '--session-dir', str(session_dir),
            '--model', f'{model}:{effort}', PROBE_MESSAGE]


def claude_result(stdout):
    """The JSON object of a `claude -p --output-format json` reply; None when stdout holds none."""
    try:
        data = json.loads(stdout)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def pi_assistant_messages(session_dir):
    messages = []
    for path in sorted(Path(session_dir).glob('*.jsonl')):
        for line in path.read_text(encoding='utf-8').splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
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
