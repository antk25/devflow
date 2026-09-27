from devflow import documents


def test_requirement_wish_and_source():
    r = documents.requirement('X (Jira: описание; пожелание)')
    assert r == {'text': 'X', 'source': 'Jira: описание; пожелание', 'wish': True}


def test_requirement_plain_and_no_source():
    assert documents.requirement('Y (ТЗ)') == {'text': 'Y', 'source': 'ТЗ', 'wish': False}
    assert documents.requirement('Z') == {'text': 'Z', 'source': '', 'wish': False}


def test_section_items_joins_wrapped_lines():
    body = '# T\n\n## Requirements\n- первое\n  продолжение (ТЗ)\n- второе (Jira: описание)\n\n## Next\n- чужое\n'
    assert documents.section_items(body, 'Requirements') == [
        'первое продолжение (ТЗ)', 'второе (Jira: описание)']


def test_section_items_missing():
    assert documents.section_items('# T\n\n## Problem\n- x\n', 'Requirements') == []


def test_requirement_source_only_from_known_prefix():
    r = documents.requirement('Кнопка (Jira: комментарий Иван (PM), 2026-09-20)')
    assert r['source'] == 'Jira: комментарий Иван (PM), 2026-09-20' and r['text'] == 'Кнопка'
    assert documents.requirement('Выгрузка отчёта (CSV)') == {'text': 'Выгрузка отчёта (CSV)', 'source': '', 'wish': False}


def _handoff(vault, name, created='2026-09-01', task='DF-1', kind='handoff', body='# Передача'):
    path = vault / 'notes' / f'{name}.md'
    path.write_text(f'---\ncreated: {created}\nproject: p\ntype: {kind}\ntask: {task}\n---\n\n{body}\n', encoding='utf-8')
    return path


def test_handoff_latest_picks_by_created_not_by_name(tmp_path):
    (tmp_path / 'notes').mkdir()
    _handoff(tmp_path, 'handoff-zzz', created='2026-09-01')
    newest = _handoff(tmp_path, 'handoff-aaa', created='2026-09-23', body='# Новая передача')
    doc = documents.handoff_latest(tmp_path)
    assert doc['path'] == str(newest) and documents.title(doc) == 'Новая передача'


def test_handoff_latest_filters_task_case_insensitively(tmp_path):
    (tmp_path / 'notes').mkdir()
    _handoff(tmp_path, 'handoff-a', created='2026-09-25', task='DF-16')
    wanted = _handoff(tmp_path, 'handoff-b', created='2026-09-20', task='DF-11')
    assert documents.handoff_latest(tmp_path, task='df-11')['path'] == str(wanted)
    assert documents.handoff_latest(tmp_path, task='DF-99') is None


def test_handoff_latest_skips_broken_frontmatter_and_other_types(tmp_path):
    (tmp_path / 'notes').mkdir()
    (tmp_path / 'notes' / 'handoff-broken.md').write_text('---\ncreated: 2026-12-31\ntype: handoff\n', encoding='utf-8')
    (tmp_path / 'notes' / 'handoff-badyaml.md').write_text('---\ncreated: 2026-12-30\ntype: [unclosed\n---\n', encoding='utf-8')
    _handoff(tmp_path, 'handoff-note', created='2026-12-29', kind='note')
    good = _handoff(tmp_path, 'handoff-good', created='2026-09-23')
    assert documents.handoff_latest(tmp_path)['path'] == str(good)


def test_handoff_latest_none_when_empty(tmp_path):
    (tmp_path / 'notes').mkdir()
    assert documents.handoff_latest(tmp_path) is None
