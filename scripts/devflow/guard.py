"""PreToolUse guard for Bash commands: deterministic deny with a suggested replacement."""
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

OPERATORS = {'&&', '||', ';', '|', '&', ';;', '|&', '\n', '(', ')', '((', '))'}
WRAPPERS = {'sudo', 'env', 'command', 'exec', 'nohup', 'time', 'nice', 'rtk'}
ASSIGNMENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')

EXTERNAL_HTTP = ('curl/wget заблокированы (защита от утечки данных). Для localhost используй '
                 '`lcurl http://localhost:<порт>/…`; внешний запрос попроси пользователя выполнить '
                 'самому: `! curl …`.')


HISTORY_REWRITE = ('Перезапись удалённой истории делает пользователь. Запушь без `--force`/`+refspec`: '
                   '`git push -u origin <ветка>`, а если нужен force — попроси пользователя выполнить его самому.')

PUSH_PROTECTED = 'Пушить можно только feature-ветку; слияние делает пользователь. Используй `git push -u origin {branch}`.'


def segments(command):
    # posix=False keeps quotes on tokens, so a quoted ';' is not taken for an operator
    lexer = shlex.shlex(command, posix=False, punctuation_chars=';&|()<>\n')
    lexer.whitespace = ' \t\r'
    lexer.whitespace_split = True
    result, current = [], []
    for token in lexer:
        if token in OPERATORS:
            if current:
                result.append(current)
            current = []
        else:
            current.append(unquote(token))
    if current:
        result.append(current)
    return [stripped for stripped in map(strip_prefix, result) if stripped]


def unquote(token):
    try:
        return ''.join(shlex.split(token)) or token
    except ValueError:
        return token


def strip_prefix(tokens):
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if ASSIGNMENT.match(token) or (index > 0 and token.startswith('-')):
            index += 1
        elif Path(token).name in WRAPPERS:
            index += 1
            if token == 'rtk' and index < len(tokens) and tokens[index] == 'proxy':
                index += 1
        else:
            break
    return tokens[index:]


def protected_branches(cwd):
    names = {'main', 'master'}
    for directory in (cwd, *cwd.parents):
        agents = directory / 'AGENTS.md'
        if agents.is_file():
            text = agents.read_text(encoding='utf-8')
            names.update(re.findall(r'^\s*-\s*(?:Base|Production) branch:\s*`([^`]+)`', text, re.M))
            break
    return names


def current_branch(cwd):
    try:
        result = subprocess.run(['git', '-C', str(cwd), 'symbolic-ref', '--quiet', '--short', 'HEAD'],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def git_output(cwd, *args):
    try:
        result = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ''
    return result.stdout.strip() if result.returncode == 0 else ''


def default_targets(cwd, branch):
    if git_output(cwd, 'config', '--get-regexp', r'^remote\..*\.push$'):
        return None
    upstream = git_output(cwd, 'config', '--get', f'branch.{branch}.merge') if branch else ''
    return [branch, upstream.removeprefix('refs/heads/')] if upstream else [branch]


def push_targets(args, branch, cwd):
    positional, forced_all = [], False
    for arg in args:
        if arg in ('--all', '--mirror'):
            forced_all = True
        elif not arg.startswith('-'):
            positional.append(arg)
    if forced_all:
        return None
    refspecs = positional[1:]
    if not refspecs:
        return default_targets(cwd, branch)
    targets = []
    for spec in refspecs:
        spec = spec.lstrip('+')
        source, _, dest = spec.partition(':')
        target = dest if dest else source
        if '*' in target:
            return None
        if target == 'HEAD':
            target = branch
        targets.append(target.removeprefix('refs/heads/') if target else None)
    return targets


def git_push_args(tokens, cwd):
    if Path(tokens[0]).name != 'git':
        return None
    index = 1
    while index < len(tokens) and tokens[index].startswith('-'):
        if tokens[index] == '-C' and index + 1 < len(tokens):
            cwd = cwd / tokens[index + 1]
            index += 2
        elif tokens[index] == '-c':
            index += 2
        else:
            index += 1
    if index < len(tokens) and tokens[index] == 'push':
        return tokens[index + 1:], cwd
    return None


def check_push(args, cwd):
    branch = current_branch(cwd)
    protected = protected_branches(cwd)
    targets = push_targets(args, branch, cwd)
    if targets is not None and not any(t is None or t in protected for t in targets):
        return None
    suggested = branch if branch and branch not in protected else '<feature-ветка>'
    return 'push-protected', PUSH_PROTECTED.format(branch=suggested)


def rewrites_history(args):
    for arg in args:
        if arg in ('--force', '-f') or arg.startswith('--force-with-lease') or arg.startswith('+'):
            return True
        if arg.startswith('-') and not arg.startswith('--') and 'f' in arg[1:]:
            return True
    return False


def decide(command, cwd):
    for tokens in segments(command):
        name = Path(tokens[0]).name
        if name in ('curl', 'wget'):
            return 'external-http', EXTERNAL_HTTP
        if name == 'cd' and len(tokens) > 1:
            cwd = cwd / tokens[1]
            continue
        push = git_push_args(tokens, cwd)
        if push:
            verdict = check_push(*push)
            if verdict:
                return verdict
            if rewrites_history(push[0]):
                return 'history-rewrite', HISTORY_REWRITE
    return None


def journal_path(env):
    return Path(env.get('DEVFLOW_GUARD_LOG') or Path.home() / '.local/share/devflow/guard.jsonl')


def log(path, entry):
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'), **entry}
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + '\n')


def run(stdin_text, env=os.environ):
    event = {}
    try:
        try:
            event = json.loads(stdin_text)
        except ValueError as exc:
            log(journal_path(env), {'rule': 'invalid-json', 'reason': str(exc), 'command': stdin_text[:500]})
            return ''
        if not isinstance(event, dict) or event.get('tool_name') != 'Bash':
            return ''
        command = (event.get('tool_input') or {}).get('command') or ''
        verdict = decide(command, Path(event.get('cwd') or '.'))
        if verdict is None:
            return ''
        rule, reason = verdict
        try:
            log(journal_path(env), {'session_id': event.get('session_id'), 'agent_type': event.get('agent_type'),
                                    'rule': rule, 'command': command, 'reason': reason})
        except OSError:
            pass
        return json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                  'permissionDecisionReason': reason}}, ensure_ascii=False)
    except Exception as exc:
        try:
            log(journal_path(env), {'session_id': event.get('session_id') if isinstance(event, dict) else None,
                                    'rule': 'error', 'reason': repr(exc)})
        except Exception:
            pass
        return ''


def main():
    output = run(sys.stdin.read())
    if output:
        print(output)
    return 0
