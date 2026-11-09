"""PreToolUse guard for Bash commands: deterministic deny with a suggested replacement."""
import json
import fnmatch
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


HEREDOC = re.compile(r'<<(-?)\s*([\'"]?)([A-Za-z_][A-Za-z0-9_]*)\2')


def strip_heredocs(command):
    kept, pending = [], []
    for line in command.split('\n'):
        if pending:
            strip_tabs, delimiter = pending[0]
            if (line.lstrip('\t') if strip_tabs else line) == delimiter:
                pending.pop(0)
            continue
        kept.append(line)
        pending = [(dash == '-', name) for dash, _, name in HEREDOC.findall(line)]
    return '\n'.join(kept)


def segments(command, posix=False):
    command = strip_heredocs(command)
    # posix=False keeps quotes on tokens, so a quoted ';' is not taken for an operator
    lexer = shlex.shlex(command, posix=posix, punctuation_chars=';&|()<>\n')
    lexer.whitespace = ' \t\r'
    lexer.whitespace_split = True
    result, current = [], []
    for token in lexer:
        if token in OPERATORS:
            if current:
                result.append(current)
            current = []
        else:
            current.append(token if posix else unquote(token))
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


def settings_paths(cwd):
    paths = [Path.home() / '.claude/settings.json']
    for directory in (*reversed(cwd.parents), cwd):
        paths.extend(directory / '.claude' / name for name in ('settings.json', 'settings.local.json'))
    return list(dict.fromkeys(paths))


def verdict(decision, rule, reason):
    return {'decision': decision, 'rule': rule, 'reason': reason}


def command_forms(command, cwd):
    return [form for group in command_groups(command, cwd) for form in group]


def command_groups(command, cwd, depth=0):
    """One list of equivalent forms per pipeline segment."""
    if depth > 8:
        raise ValueError('Слишком много вложенных оболочек')
    # Arbitrary shell evaluation is not a permission boundary: require confirmation.
    quote = None
    for char in command:
        if quote == "'":
            if char == "'":
                quote = None
            continue
        if char in '`$\\' or (quote is None and char in '<>'):
            raise ValueError('Подстановка, перенаправление или escape требует подтверждения')
        if char == '"':
            quote = None if quote == '"' else '"'
        elif char == "'" and quote is None:
            quote = "'"
    if quote is not None:
        raise ValueError('Незакрытая кавычка')
    if re.search(r'\b(?:env|sudo|nice|nohup|time|rtk|exec)\s+-', command):
        raise ValueError('Опции обёртки требуют отдельного простого вызова')
    groups = []
    for tokens in segments(command, posix=True):
        name = Path(tokens[0]).name
        if name in ('eval', 'source', '.'):
            raise ValueError('Динамическая команда требует подтверждения')
        if name == 'cd' and len(tokens) == 2:
            cwd = (cwd / Path(tokens[1]).expanduser()).resolve()
            continue
        if name in ('bash', 'sh', 'zsh', 'dash') and any(t.startswith('-') and 'c' in t for t in tokens[1:]) and '-c' not in tokens:
            raise ValueError('Составные опции оболочки не поддерживаются')
        if name in ('bash', 'sh', 'zsh', 'dash') and '-c' in tokens:
            index = tokens.index('-c')
            if index != 1 or index + 2 != len(tokens):
                raise ValueError('Неоднозначный вызов оболочки')
            groups.extend(command_groups(tokens[index + 1], cwd, depth + 1))
            continue
        normalized = [str(Path(t).expanduser()) if t.startswith('~/') else t for t in tokens]
        if name in ('git', 'gh', 'curl', 'wget', 'ssh', 'scp', 'rsync', 'bash', 'sh', 'claude', 'claude-bridge'):
            normalized[0] = name
        forms = [(' '.join(normalized), cwd)]
        groups.append(forms)
        if name in ('bash', 'sh') and len(normalized) > 1 and not normalized[1].startswith('-'):
            forms.append((' '.join(normalized[1:]), cwd))
        if name == 'git':
            index = 1
            while index < len(tokens) and tokens[index].startswith('-'):
                if tokens[index] == '-C' and index + 1 < len(tokens):
                    cwd = (cwd / Path(tokens[index + 1]).expanduser()).resolve()
                    index += 2
                elif tokens[index] == '-c':
                    index += 2
                elif tokens[index] in ('--no-pager', '--no-optional-locks'):
                    index += 1
                else:
                    raise ValueError('Неизвестная глобальная опция git')
            forms.append((' '.join(['git', *tokens[index:]]), cwd))
    return groups


def rule_matches(rule, tool, value, cwd):
    match = re.fullmatch(r'([\w*_-]+)(?:\((.*)\))?', rule)
    if not match:
        raise ValueError(f'Неподдерживаемое правило: {rule}')
    name, pattern = match.groups()
    if not fnmatch.fnmatchcase(tool, name):
        return False
    if pattern is None:
        return True
    if tool == 'Bash':
        pattern = pattern.replace('~/', str(Path.home()) + '/')
        # The integration script can be invoked directly or through bash.
        values = [value]
        if pattern.startswith(('bash ', 'sh ')):
            values.append(pattern.split(' ', 1)[0] + ' ' + value)
        if pattern.endswith(':*'):
            prefix = pattern[:-2]
            return any(v == prefix or v.startswith(prefix + ' ') for v in values)
        patterns = [pattern, pattern.replace(' * ', ' ')]
        return any(fnmatch.fnmatchcase(v, p) for v in values for p in patterns)
    if tool in ('Read', 'Write', 'Edit', 'Glob', 'Grep'):
        path = (cwd / Path(value).expanduser()).resolve()
        if pattern in ('*', '**'):
            return True
        if pattern.startswith('//'):
            pattern = pattern[1:]
        elif pattern.startswith('~/'):
            pattern = str(Path(pattern).expanduser())
        elif pattern.startswith('/'):
            pattern = str(cwd / pattern.lstrip('/'))
        else:
            pattern = str(cwd / pattern)
        patterns = [pattern]
        while any('/**/' in p for p in patterns[-1:]):
            patterns.append(patterns[-1].replace('/**/', '/', 1))
        return any(fnmatch.fnmatchcase(str(path), p) for p in patterns)
    raise ValueError(f'Неподдерживаемый аргумент правила: {rule}')


def permission_decision(event, settings_paths):
    try:
        tool = event.get('tool_name', event.get('toolName'))
        tool = {'bash': 'Bash', 'read': 'Read', 'write': 'Write', 'edit': 'Edit',
                'find': 'Glob', 'ls': 'Glob', 'grep': 'Grep'}.get(tool, tool)
        data = event.get('tool_input', event.get('input', {}))
        cwd = Path(event.get('cwd') or '.').resolve()
        if not isinstance(tool, str) or not isinstance(data, dict):
            raise ValueError('Некорректное событие инструмента')
        rules = {'allow': [], 'ask': [], 'deny': []}
        for path in settings_paths:
            if not path.exists():
                continue
            settings = json.loads(path.read_text(encoding='utf-8'))
            permissions = settings.get('permissions', {})
            for action in rules:
                entries = permissions.get(action, [])
                if not isinstance(entries, list) or not all(isinstance(r, str) for r in entries):
                    raise ValueError(f'Некорректные permissions.{action}: {path}')
                base = path.parent.parent if path.parent.name == '.claude' and path.parent.parent != Path.home() else cwd
                rules[action].extend((entry, base) for entry in entries)
            soft = settings.get('autoMode', {}).get('soft_deny', [])
            if not isinstance(soft, list) or not all(isinstance(r, str) for r in soft):
                raise ValueError(f'Некорректные autoMode.soft_deny: {path}')
            rules['ask'].extend((r, cwd) for r in soft if r != '$defaults')
        if tool == 'Bash':
            command = data.get('command')
            if not isinstance(command, str):
                raise ValueError('Отсутствует command')
            try:
                groups = command_groups(command, cwd)
                forms = [form for group in groups for form in group]
            except ValueError as exc:
                return verdict('deny', 'shell-uncertain', f'{exc}; упростите вызов до отдельных команд без вычислений оболочки.')
            for value, directory in forms:
                if Path(value.split(' ', 1)[0]).name in ('claude', 'claude-bridge'):
                    return verdict('deny', 'claude-host', 'Из pi нельзя вызывать Claude Code; используйте devflow phase run.')
                blocked = decide(value, directory)
                if blocked:
                    return verdict('deny', *blocked)
                if value.startswith('git push'):
                    args = value.split()[2:]
                    targets = push_targets(args, current_branch(directory), directory)
                    if targets and 'production' in targets:
                        return verdict('deny', 'push-production', 'Публикацию в production выполняет пользователь.')
                    if any(a in ('--delete', '-d', '--mirror') or a.startswith((':', '--delete=', '--mirror=')) or
                           (a.startswith('-') and not a.startswith('--') and 'd' in a[1:]) for a in args):
                        return verdict('deny', 'push-delete', 'Удаление и зеркалирование выполняет пользователь.')
        else:
            forms = [(data.get('path', data.get('file_path', '')), cwd)]
            groups = [forms]
        matches = {}
        for action in ('deny', 'ask', 'allow'):
            for rule, base in rules[action]:
                hit = lambda group: any(rule_matches(rule, tool, value if tool == 'Bash' else str((directory / Path(value).expanduser()).resolve()),
                                                     directory if tool == 'Bash' else base) for value, directory in group)
                # An allowed segment must not carry the rest of a compound command through.
                if (all if action == 'allow' else any)(hit(group) for group in groups):
                    matches[action] = rule
                    break
        for action in ('deny', 'ask', 'allow'):
            if action in matches:
                return verdict(action, matches[action], 'Правило действующих настроек; для отказа измените запрос, не повторяйте его автоматически.')
        return verdict('allow', 'pi-default', 'Явных ограничений нет; обычное поведение pi.')
    except Exception as exc:
        return verdict('deny', 'settings-error', f'Проверка политики не выполнена: {exc}; исправьте настройки.')


def main():
    if sys.argv[1:] in (['--host', 'pi'], ['guard', '--host', 'pi']):
        try:
            event = json.loads(sys.stdin.read())
            cwd = Path(event.get('cwd') or '.').resolve()
            output = permission_decision(event, settings_paths(cwd))
        except Exception as exc:
            output = verdict('deny', 'guard-error', f'Проверка недоступна: {exc}; исправьте настройки guard.')
        print(json.dumps(output, ensure_ascii=False))
        return 0
    output = run(sys.stdin.read())
    if output:
        print(output)
    return 0
