"""Context compaction as a session cut: automatic hand-off, summary instructions, context levels."""
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

from .documents import WorkflowError, document, resolve_slug
from .storage import atomic_write

WARN_TOKENS = 120000
CUT_TOKENS = 180000


def context_level(tokens, window=None, session=None):
    if tokens is None:
        return {'level': 'unknown', 'tokens': None, 'text': ''}
    k = tokens // 1000
    if tokens >= CUT_TOKENS:
        sid = f' (во frontmatter `session: {session}`)' if session else ''
        text = (f'CONTEXT_CUT {k}K — первое действие этого хода, без спроса: Skill cut в режиме CONTEXT_CUT (передача '
                f'в `notes/handoff-<slug>.md`{sid}), если в этой сессии её ещё не писали; потом продолжай '
                f'запрос. Новую большую работу не начинай: предложи /clear.')
        return {'level': 'cut', 'tokens': tokens, 'text': text}
    if tokens >= WARN_TOKENS or (window and tokens >= 0.75 * window):
        return {'level': 'warn', 'tokens': tokens,
                'text': f'CONTEXT_WARN {k}K — закончи текущий шаг и держи передачу актуальной.'}
    return {'level': 'ok', 'tokens': tokens, 'text': ''}


def _known(vault, slug):
    try:
        slug = resolve_slug(vault, slug)
    except WorkflowError:
        return None
    for folder in ('tz', 'research', 'plans', 'changelog'):
        for path in (vault / folder).glob('*.md'):
            stem = re.sub(r'^\d{4}-\d{2}-\d{2}-', '', path.stem.lower()) if folder == 'changelog' else path.stem.lower()
            if stem == slug:
                return slug
    return None


def _ledger():
    from . import transcripts
    return transcripts.load_ledger()


def session_slug(vault, session):
    if not session:
        return None
    entries = _ledger().get(session)
    if not entries:
        return None
    task = sorted(entries, key=lambda e: (e[0] is not None, e[0] or datetime.min))[-1][1]
    return _known(Path(vault), task.lower())


def _git(cwd, *args):
    try:
        out = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.rstrip('\n') if out.returncode == 0 else None


def branch_slug(vault, cwd):
    branch = _git(cwd, 'branch', '--show-current')
    if not branch or branch in ('main', 'master'):
        return None
    last = branch.rsplit('/', 1)[-1].lower()
    if re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*', last):
        found = _known(Path(vault), last)
        if found:
            return found
    key = re.search(r'[a-z]+-\d+', last)
    return _known(Path(vault), key[0]) if key else None


def find_session_handoff(vault, slug, session):
    for path in sorted((Path(vault) / 'notes').glob(f'handoff-{slug}*.md')):
        try:
            meta = document(path)['meta']
        except Exception:
            continue
        if str(meta.get('task', '')).lower() == slug and str(meta.get('session', '')) == session:
            return path
    return None


def _unclaimed_fresh(path, now, minutes=30):
    # A /cut hand-off without `session` written moments ago belongs to the session being compacted.
    try:
        meta = document(path)['meta']
    except Exception:
        return False
    return not meta.get('session') and now.timestamp() - path.stat().st_mtime < minutes * 60


def _route(cwd, slug):
    if not (Path(cwd) / '.devflow/project.json').exists():
        return None
    try:
        from .documents import context
        from .storage import connect
        from .workflow import task_state
        ctx = context(cwd)
        db = connect(ctx, create=False)
        try:
            state = task_state(ctx, db, slug)
        finally:
            db.close()
        return f"{state.get('state')} / {state.get('phase')}"
    except Exception:
        return None


def _block(cwd, slug, trigger, now):
    lines = [f'## Автоматически при сжатии {now:%Y-%m-%d %H:%M} ({trigger})', '',
             'Записано автоматически, без тупиков и решений.', '']
    branch = _git(cwd, 'branch', '--show-current')
    if branch:
        lines.append(f'- Ветка: `{branch}`')
    route = _route(cwd, slug)
    if route:
        lines.append(f'- Route: {route}')
    log = _git(cwd, 'log', '--oneline', '-5')
    if log:
        lines += ['', 'Последние коммиты:', '```', log, '```']
    status = _git(cwd, 'status', '--short')
    if status:
        lines += ['', 'Незакоммиченное:', '```', '\n'.join(status.splitlines()[:20]), '```']
    return '\n'.join(lines) + '\n'


def write_auto_handoff(vault, cwd, slug, session, trigger, now):
    notes = Path(vault) / 'notes'
    block = _block(cwd, slug, trigger, now)
    existing = find_session_handoff(vault, slug, session)
    if existing:
        raw = existing.read_text(encoding='utf-8')
        atomic_write(existing, raw + ('' if raw.endswith('\n') else '\n') + '\n' + block)
        return existing, 'appended'
    path = notes / f'handoff-{slug}.md'
    if path.exists() and _unclaimed_fresh(path, now):
        raw = path.read_text(encoding='utf-8')
        atomic_write(path, raw + ('' if raw.endswith('\n') else '\n') + '\n' + block)
        return path, 'appended'
    if path.exists():
        path = notes / f'handoff-{slug}-auto-{session}.md'
    project = Path(cwd).name
    try:
        from .documents import context
        project = context(cwd)['project']
    except Exception:
        pass
    text = (f'---\ncreated: {now:%Y-%m-%d}\nproject: {project}\ntype: handoff\ntask: {slug}\n'
            f'session: {session}\ntags: [передача, {slug}]\n---\n\n'
            f'# {slug} — передача {now:%Y-%m-%d %H:%M}\n\n' + block)
    atomic_write(path, text)
    return path, 'created'


def summary_instructions(handoff=None):
    lines = ['При сжатии сохрани в сводке: тупики с причинами (что проверено и не сработало),',
             'решения этой сессии, которых нет в плане, и одно конкретное следующее действие.']
    if handoff:
        lines += [f'Передача задачи: {handoff}', 'После сжатия прочитай её и продолжай со «Следующего шага».']
    return '\n'.join(lines)


def auto(ctx, session, trigger, cwd, tokens=None, host=None, now=None):
    now = now or datetime.now()
    vault = Path(ctx['vault'])
    slug = session_slug(vault, session) or branch_slug(vault, cwd)
    log = Path.home() / '.claude' / 'devflow' / 'compact-log.jsonl'
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8') as fh:
        fh.write(json.dumps({'ts': now.isoformat(timespec='seconds'), 'host': host, 'session': session,
                             'trigger': trigger, 'tokens': tokens, 'slug': slug}, ensure_ascii=False) + '\n')
    if not slug:
        return {'slug': None, 'path': None, 'action': 'none', 'instructions': summary_instructions()}
    path, action = write_auto_handoff(vault, cwd, slug, session, trigger, now)
    return {'slug': slug, 'path': str(path), 'action': action, 'instructions': summary_instructions(path)}
