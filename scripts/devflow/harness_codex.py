"""codex exec as a phase harness: command line and JSONL event parsing."""
import json
from pathlib import Path

JIRA = Path(__file__).resolve().parents[2] / 'integrations' / 'jira-issue.sh'


def prompt(body, message):
    # Codex has no Skill tool: the agent body travels in the prompt and Jira goes through the read-only script.
    return (f'{body.strip()}\n\n---\nСкилла /jira здесь нет: задачу Jira читать `{JIRA} <KEY>`.\n\n{message}')


def build_command(model, effort, message, cwd, add_dirs=()):
    if not model:
        raise ValueError('codex model must be explicit')
    cmd = ['codex', 'exec', '--json', '-m', model, '-s', 'workspace-write', '-C', str(cwd)]
    if effort:
        cmd += ['-c', f'model_reasoning_effort={effort}']
    for path in add_dirs:
        cmd += ['--add-dir', str(path)]
    return cmd + ['--', message]


def parse(stdout, stderr, exit_code):
    events = []
    for line in (stdout or '').splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            events.append(item)
    thread, report, tokens, completed, failed = None, '', None, False, False
    for event in events:
        kind = event.get('type')
        if kind == 'thread.started':
            thread = event.get('thread_id')
        elif kind == 'item.completed' and (event.get('item') or {}).get('type') == 'agent_message':
            report = str(event['item'].get('text') or '')
        elif kind == 'turn.completed':
            completed = True
            usage = event.get('usage') or {}
            tokens = (tokens or 0) + sum(int(usage.get(k) or 0) for k in (
                'input_tokens', 'cached_input_tokens', 'output_tokens', 'reasoning_output_tokens'))
        elif kind in ('turn.failed', 'error'):
            failed = True
    ok = exit_code == 0 and completed and not failed
    return {'status': 'ok' if ok else 'failed', 'tokens': tokens, 'cost': None, 'session_id': thread,
            'report': report or stdout}
