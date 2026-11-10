import json
import sys
from devflow import cli, documents


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


def test_section_keeps_prose_and_sublist_cuts_next_section():
    body = '# T\n\n## Requirements\nПроза.\n\n- пункт\n  - подпункт\n\n## Next\n- чужое\n'
    assert documents.section(body, 'Requirements') == 'Проза.\n\n- пункт\n  - подпункт\n\n'
    assert documents.section(body, 'Absent') == ''


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


def test_handoff_full_slug_and_legacy_jira(tmp_path):
    (tmp_path / 'notes').mkdir()
    (tmp_path / 'plans').mkdir()
    (tmp_path / 'plans/df-11-pi.md').write_text('# Plan')
    old = _handoff(tmp_path, 'handoff-df-11', task='DF-11')
    assert documents.handoff_latest(tmp_path, 'df-11-pi')['path'] == str(old)
    full = _handoff(tmp_path, 'handoff-df-pi-workflow-parity', task='df-pi-workflow-parity')
    assert documents.handoff_latest(tmp_path, 'df-pi-workflow-parity')['path'] == str(full)
    assert documents.handoff_latest(tmp_path, 'df-11')['path'] == str(old)


def test_handoff_ambiguity_never_selects_newest_foreign_task(tmp_path):
    import pytest
    (tmp_path / 'notes').mkdir()
    _handoff(tmp_path, 'handoff-a', task='df-pi-workflow-parity')
    _handoff(tmp_path, 'handoff-b', task='other-task', created='2026-10-01')
    with pytest.raises(documents.WorkflowError, match='Ambiguous handoff'):
        documents.handoff_latest(tmp_path)
    assert documents.handoff_latest(tmp_path, 'missing-task') is None
    (tmp_path / 'plans').mkdir()
    for name in ('df-11-a', 'df-11-b'):
        (tmp_path / f'plans/{name}.md').write_text('# Plan')
    _handoff(tmp_path, 'handoff-df-11', task='DF-11')
    with pytest.raises(documents.WorkflowError, match='Ambiguous task'):
        documents.handoff_latest(tmp_path, 'df-11-a')


def test_handoff_legacy_key_with_distinct_full_filenames_is_ambiguous(tmp_path):
    import pytest
    (tmp_path / 'notes').mkdir()
    for slug in ('df-11-a', 'df-11-b'):
        _handoff(tmp_path, f'handoff-{slug}', task='DF-11')
    with pytest.raises(documents.WorkflowError, match='Ambiguous handoff'):
        documents.handoff_latest(tmp_path)
    assert documents.handoff_latest(tmp_path, 'df-11-a')['path'].endswith('handoff-df-11-a.md')


def test_handoff_latest_none_when_empty(tmp_path):
    (tmp_path / 'notes').mkdir()
    assert documents.handoff_latest(tmp_path) is None


def test_step_criteria_keeps_browser_item_verbatim():
    item = 'browser: env: staging; Дано товар в корзине; Когда открыть /cart; Тогда виден итог'
    section = f'### s: Шаг\n- **Acceptance:**\n  - pytest зелёный\n  - {item}\n- **Files:** a\n'
    assert documents.step_criteria(section) == ['pytest зелёный', item]


def test_context_without_agents_md_is_human_readable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['devflow', '--cwd', str(tmp_path), 'context'])
    assert cli.main() == 1
    err = json.loads(capsys.readouterr().err)
    assert err['state'] == 'invalid'
    assert 'No AGENTS.md' in err['error'] and '/project init' in err['error']
    assert 'Errno' not in err['error']


def _project(root, vault, name='p'):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'AGENTS.md').write_text(f'---\nproject: {name}\nvault: {vault}\n---\n', encoding='utf-8')


def test_context_found_from_nested_subdirectory(tmp_path):
    vault = tmp_path / 'vault'
    vault.mkdir()
    _project(tmp_path / 'root', vault)
    nested = tmp_path / 'root' / 'a' / 'b'
    nested.mkdir(parents=True)
    ctx = documents.context(nested)
    assert ctx['cwd'] == (tmp_path / 'root').resolve()
    assert ctx['vault'] == vault.resolve()


def test_context_relative_vault_resolved_from_project_root(tmp_path):
    (tmp_path / 'root' / 'notes').mkdir(parents=True)
    _project(tmp_path / 'root', 'notes')
    nested = tmp_path / 'root' / 'sub'
    nested.mkdir()
    assert documents.context(nested)['vault'] == (tmp_path / 'root' / 'notes').resolve()


def test_context_nearest_agents_md_wins(tmp_path):
    vault = tmp_path / 'vault'
    vault.mkdir()
    _project(tmp_path / 'root', vault, 'outer')
    _project(tmp_path / 'root' / 'inner', vault, 'inner')
    (tmp_path / 'root' / 'inner' / 'x').mkdir()
    ctx = documents.context(tmp_path / 'root' / 'inner' / 'x')
    assert ctx['project'] == 'inner' and ctx['cwd'] == (tmp_path / 'root' / 'inner').resolve()


def test_tz_under_jira_key_found_by_full_slug(tmp_path):
    (tmp_path / 'tz').mkdir()
    (tmp_path / 'tz' / 'SE-2298.md').write_text('# SE-2298\n', encoding='utf-8')
    found = documents.artifact(tmp_path, 'tz', 'se-2298-collections-from-page')
    assert found['path'].endswith('SE-2298.md')
    assert documents.artifact(tmp_path, 'research', 'se-2298-collections-from-page') is None
    assert documents.artifact(tmp_path, 'tz', 'se-22981-other') is None
