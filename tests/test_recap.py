import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.devflow import recap
from scripts.devflow.transcripts import Msg

NOW = datetime(2026, 10, 13, 7, 0, tzinfo=timezone.utc)
KEY_RE = re.compile(r'\b(?:AB)-\d{1,5}\b', re.I)

CHANGELOG = """# AB-1

## Шаг 1 — old · 2026-10-10
Старое.

## Шаг 2 — new · 2026-10-12
### Что сделано
Новое.
### Files
- a.py
### Tests
- ok
### Notes for review
- Отклонение: X.
"""


def msg(text, hours_ago, session='s1', cwd=None):
    return Msg(NOW - timedelta(hours=hours_ago), cwd or str(Path.home() / 'projects/app'), session, text)


def test_step_sections_keeps_steps_from_since_day_without_files_and_tests():
    out = recap.step_sections(CHANGELOG, '2026-10-12')
    assert 'Новое.' in out and 'Отклонение: X.' in out
    assert 'Старое.' not in out and 'a.py' not in out and '- ok' not in out


def test_changelogs_find_key_in_file_name(tmp_path):
    (tmp_path / 'changelog').mkdir()
    (tmp_path / 'changelog/2026-10-12-ab-1-thing.md').write_text(CHANGELOG)
    (tmp_path / 'changelog/2026-10-12-ab-2-stale.md').write_text('## Шаг 1 — x · 2026-10-01\nстарьё')
    assert list(recap.changelogs({'app': tmp_path}, KEY_RE, '2026-10-12')) == ['AB-1']


def test_task_messages_skip_harness_noise_and_cut_pasted_content():
    msgs = [msg('берусь за AB-1', 3), msg('<command-name>/effort</command-name>', 2),
            msg('вот лог <pasted_content id="x">секрет</pasted_content id="x"> почини', 1),
            msg('берусь за AB-1', 0.5), msg(recap.PROMPT.format(hours=24, materials='## AB-1'), 0.2), msg('вчерашнее про AB-1', 30, session='s2')]
    out = recap.task_messages(msgs, {}, NOW - timedelta(hours=24), KEY_RE)
    assert out == {'AB-1': ['берусь за AB-1', 'вот лог [вставка] почини']}


def test_build_asks_model_once_and_saves_by_moscow_day(tmp_path):
    prompts = []
    fetch = lambda since, until: ([msg('делаю AB-1, падает тест', 2)], {})
    out = recap.build({'tasks': [{'key': 'AB-1', 'title': 'Задача', 'project': 'app'}]}, {'projects': {}}, KEY_RE, tmp_path,
                      now=NOW, fetch=fetch, ask=lambda p: prompts.append(p) or '### AB-1 — Задача')
    assert len(prompts) == 1 and 'падает тест' in prompts[0] and 'AB-1 — Задача' in prompts[0]
    assert out['keys'] == ['AB-1'] and Path(out['path']) == tmp_path / 'recap/2026-10-13.md'
    assert '### AB-1 — Задача' in Path(out['path']).read_text()


def test_build_without_work_does_not_call_model(tmp_path):
    out = recap.build({'tasks': []}, {'projects': {}}, KEY_RE, tmp_path, now=NOW,
                      fetch=lambda s, u: ([], {}), ask=lambda p: 1 / 0)
    assert out['path'] is None and out['keys'] == []
