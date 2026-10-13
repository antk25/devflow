"""Сводка к ежедневному созвону: что делал за сутки, какие были проблемы и как решены."""
import re
import shutil
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .documents import context
from .storage import atomic_write
from .transcripts import NO_TASK, assign_tasks, project_of

MSK = timezone(timedelta(hours=3))
STEP = re.compile(r'^## .*?(\d{4}-\d{2}-\d{2})', re.M)
SKIP_SECTIONS = re.compile(r'^### (Files|Tests)\b.*?(?=^##|\Z)', re.M | re.S)
NOISE = ('<', 'Base directory for this skill', 'Another Claude session', '[Request interrupted', 'Caveat:', 'Ниже материалы по задачам')
PASTED = re.compile(r'<pasted_content[^>]*>.*?(</pasted_content[^>]*>|\Z)', re.S)
CHANGELOG_CHARS = 5000
MESSAGE_CHARS = 400
MESSAGES_CHARS = 3000
MODEL = 'sonnet'
TIMEOUT = 300

PROMPT = """Ниже материалы по задачам, которыми разработчик занимался за последние {hours} ч: шаги из changelog
и его собственные реплики ассистенту. Составь сводку для ежедневного созвона (10–15 минут на всю команду).

Формат — markdown, по задаче на блок:
### <КЛЮЧ> — <короткое название>
- **Сделано:** 1–2 предложения, по сути, без имён файлов и классов, если они не важны для команды.
- **Проблема → решение:** только если проблема была; одна строка на проблему. Нет проблем — пункт опустить.
- **Дальше:** одна строка, если из материалов видно, что осталось.

Пиши по-русски, коротко, так, чтобы можно было прочитать вслух. Ничего не выдумывай: чего нет в материалах — не пиши.
Задачи без содержательной работы (одно упоминание ключа) объедини в конце строкой «**Также касался:** …»; если таких нет — строку не пиши.

{materials}"""


def step_sections(text: str, since_day: str) -> str:
    """Шаги changelog с датой в заголовке ≥ since_day, без разделов Files и Tests."""
    marks = list(STEP.finditer(text))
    parts = [text[m.start():marks[i + 1].start() if i + 1 < len(marks) else len(text)]
             for i, m in enumerate(marks) if m.group(1) >= since_day]
    return SKIP_SECTIONS.sub('', ''.join(parts)).strip()[:CHANGELOG_CHARS]


def changelogs(vaults: dict[str, Path], key_re: re.Pattern, since_day: str) -> dict[str, str]:
    """{KEY: шаги за период} по changelog/*.md всех vault; имя файла начинается с даты, ключ — в имени."""
    out: dict[str, list[str]] = defaultdict(list)
    for vault in vaults.values():
        for path in sorted((vault / 'changelog').glob('*.md')):
            key = key_re.search(path.stem.upper())
            if key and (steps := step_sections(path.read_text(encoding='utf-8', errors='ignore'), since_day)):
                out[key.group(0)].append(steps)
    return {k: '\n\n'.join(v) for k, v in out.items()}


def spoken(text: str) -> str:
    """Реплика человека без служебных вставок харнеса; служебная целиком — пустая строка."""
    text = text.strip()
    if text.startswith(NOISE):
        return ''
    return PASTED.sub('[вставка]', text).strip()[:MESSAGE_CHARS]


def task_messages(msgs, ledger: dict, since: datetime, key_re: re.Pattern) -> dict[str, list[str]]:
    """{KEY: [свои реплики с since]}: задача реплики — по журналу драйвера и упоминаниям ключа в сессии, как в табеле."""
    by_session = defaultdict(list)
    for m in msgs:
        by_session[m.session].append(m)
    out: dict[str, list[str]] = defaultdict(list)
    for sid, items in by_session.items():
        items.sort(key=lambda m: m.ts)
        marks = list(ledger.get(sid, [])) + [(m.ts, k.group(0).upper()) for m in items for k in key_re.finditer(m.text[:8000])]
        rows = [{'ts': m.ts, 'cwd': m.cwd} for m in items]
        assign_tasks(rows, marks)
        for m, r in zip(items, rows):
            if r['task'] != NO_TASK and m.ts >= since and project_of(m.cwd) and (text := spoken(m.text)) \
                    and text not in out[r['task']]:
                out[r['task']].append(text)
    return out


def materials(tasks: list[dict], logs: dict[str, str], said: dict[str, list[str]]) -> str:
    by_key = {t['key']: t for t in tasks if t.get('key')}
    blocks = []
    for key in sorted(set(logs) | set(said)):
        t = by_key.get(key, {})
        head = f"## {key} — {t.get('title') or 'без задачи в vault'}"
        meta = [f"проект: {t['project']}" if t.get('project') else '', f"стадия: {t['stage']['group']}" if t.get('stage') else '',
                f"PR: {t['open_pr']}" if t.get('open_pr') else '']
        lines = [head, ', '.join(m for m in meta if m)]
        if logs.get(key):
            lines += ['### Changelog за период', logs[key]]
        if said.get(key):
            text, size = [], 0
            for s in said[key]:
                if size + len(s) > MESSAGES_CHARS:
                    break
                text.append(f'- {s}')
                size += len(s)
            lines += ['### Реплики разработчика', *text]
        blocks.append('\n'.join(line for line in lines if line))
    return '\n\n'.join(blocks)


def ask_model(prompt: str) -> str:
    claude = shutil.which('claude')
    if not claude:
        raise RuntimeError('claude не найден в PATH')
    done = subprocess.run([claude, '-p', '--model', MODEL], input=prompt, capture_output=True, text=True, timeout=TIMEOUT)
    if done.returncode or not done.stdout.strip():
        raise RuntimeError((done.stderr or done.stdout).strip()[-500:] or f'claude завершился с кодом {done.returncode}')
    return done.stdout.strip()


def build(snapshot: dict, registry: dict, key_re: re.Pattern | None, state: Path, now: datetime | None = None,
          hours: int = 24, fetch=None, ask=ask_model) -> dict:
    """{markdown, path, keys}: сводка за hours часов сохраняется в <state>/recap/<день МСК>.md."""
    from .board import messages
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    if key_re is None:
        return {'markdown': 'Задач с ключами нет — сводить нечего.', 'path': None, 'keys': []}
    vaults = {}
    for name, entry in registry['projects'].items():
        try:
            vaults[name] = context(Path(entry['path']))['vault']
        except Exception:
            continue
    logs = changelogs(vaults, key_re, since.astimezone(MSK).strftime('%Y-%m-%d'))
    msgs, ledger = (fetch or messages)(since - timedelta(hours=12), now)
    said = task_messages(msgs, ledger, since, key_re)
    keys = sorted(set(logs) | set(said))
    if not keys:
        return {'markdown': f'За последние {hours} ч работы по задачам не найдено.', 'path': None, 'keys': []}
    text = ask(PROMPT.format(hours=hours, materials=materials(snapshot.get('tasks', []), logs, said)))
    stamp = now.astimezone(MSK)
    markdown = f"# Сводка к созвону — {stamp:%d.%m.%Y %H:%M} МСК, за {hours} ч\n\n{text}\n"
    path = state / 'recap' / f'{stamp:%Y-%m-%d}.md'
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, markdown)
    return {'markdown': markdown, 'path': str(path), 'keys': keys}
