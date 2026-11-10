"""claude -p as a phase harness: command line and result parsing, shared with the benchmark."""
import json


def result(stdout):
    """The JSON object of a `claude -p --output-format json` reply; None when stdout holds none."""
    try:
        data = json.loads(stdout)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def usage(data):
    """Token totals over `modelUsage` of a reply, the dominant model by cost and the total cost."""
    models = (data or {}).get('modelUsage') or {}
    totals = {'input': 0, 'output': 0, 'reasoning': 0, 'cache_read': 0, 'cache_write': 0}
    for item in models.values():
        totals['input'] += int(item.get('inputTokens') or 0)
        totals['output'] += int(item.get('outputTokens') or 0)
        totals['reasoning'] += int(item.get('thinkingTokens') or 0)
        totals['cache_read'] += int(item.get('cacheReadInputTokens') or 0)
        totals['cache_write'] += int(item.get('cacheCreationInputTokens') or 0)
    dominant = max(models, key=lambda m: float(models[m].get('costUSD') or 0), default=None)
    return totals, dominant, float((data or {}).get('total_cost_usd') or 0)


def build_command(agent, model, effort, tools, message, add_dirs=()):
    # `--allowedTools` and `--add-dir` are variadic, so the message goes right after `-p`.
    cmd = ['claude', '-p', message, '--agent', agent, '--model', model]
    if effort:
        cmd += ['--effort', effort]
    # The global allow for `devflow approve` is for the main session at the gate; a phase never approves itself.
    cmd += ['--output-format', 'json', '--permission-mode', 'acceptEdits', '--allowedTools', ','.join(tools),
            '--disallowedTools', 'Bash(devflow approve:*)']
    for path in add_dirs:
        cmd += ['--add-dir', str(path)]
    return cmd


def parse(stdout, stderr, exit_code):
    data = result(stdout)
    if data is None:
        return {'status': 'failed', 'tokens': None, 'cost': None, 'session_id': None, 'report': stdout}
    totals, _, cost = usage(data)
    ok = exit_code == 0 and not data.get('is_error')
    return {'status': 'ok' if ok else 'failed', 'tokens': sum(totals.values()), 'cost': cost,
            'session_id': data.get('session_id'), 'report': str(data.get('result') or '')}
