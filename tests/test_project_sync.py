import json
from pathlib import Path

import pytest

from devflow.documents import WorkflowError
from devflow.project import init, sync
from devflow.registry import load

from test_project_init import checksums, draft_for, root  # noqa: F401


def register(root, name, path):
    registry = root / '.claude/data/projects.json'
    data = load(registry)
    data['projects'][name] = {'path': str(path), 'description': ''}
    registry.write_text(json.dumps(data))


def agents_only(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    vault = tmp_path / 'vault' / name
    (path / 'AGENTS.md').write_text(f'---\nproject: {name}\nvault: {vault}\n---\n\n# {name}\n\n## What\nТест.\n')
    return path


def by_project(reports):
    return {r['project']: {i['item']: i['status'] for i in r['items']} for r in reports}


@pytest.fixture
def three(root, tmp_path):
    full = tmp_path / 'full'
    full.mkdir()
    draft, _ = draft_for(tmp_path, 'full')
    init(full, None, root, draft)
    bare = agents_only(tmp_path, 'bare')
    register(root, 'bare', bare)
    register(root, 'gone', tmp_path / 'gone')
    return {'full': full, 'bare': bare}


def test_dry_run_reports_and_writes_nothing(root, three, tmp_path):
    before = checksums(tmp_path)
    reports = sync(all_projects=True, root=root, dry_run=True)
    assert [r['project'] for r in reports] == ['full', 'bare', 'gone']
    got = by_project(reports)
    assert set(got['full'].values()) == {'skipped'}
    assert got['bare']['identity'] == 'create' and got['bare']['database'] == 'create'
    assert got['gone'] == {'path': 'attention'}
    assert checksums(tmp_path) == before
    assert not (three['bare'] / '.devflow').exists()


def test_apply_creates_only_what_was_reported(root, three, tmp_path):
    full_before = checksums(three['full'], tmp_path / 'vault' / 'full')
    reports = sync(all_projects=True, root=root)
    got = by_project(reports)
    assert set(got['full'].values()) == {'skipped'}
    assert got['bare']['identity'] == 'created' and got['bare']['database'] == 'created'
    assert got['bare']['agents_md'] == 'skipped' and got['bare']['registry'] == 'skipped'
    assert got['gone'] == {'path': 'attention'}
    ident = json.loads((three['bare'] / '.devflow/project.json').read_text())['id']
    assert (tmp_path / 'state' / ident / 'state.sqlite3').exists()
    assert (tmp_path / 'vault/bare/plans').is_dir()
    assert checksums(three['full'], tmp_path / 'vault' / 'full') == full_before
    assert load(root / '.claude/data/projects.json')['projects']['gone']['path'] == str(tmp_path / 'gone')


def test_missing_agents_md_is_attention_and_never_generated(root, tmp_path):
    path = tmp_path / 'empty'
    path.mkdir()
    register(root, 'empty', path)
    reports = sync(['empty'], root=root)
    assert by_project(reports)['empty'] == {'agents_md': 'attention'}
    assert list(path.iterdir()) == []


def test_identity_without_database_is_attention(root, tmp_path, monkeypatch):
    path = agents_only(tmp_path, 'orphan')
    register(root, 'orphan', path)
    (path / '.devflow').mkdir()
    (path / '.devflow/project.json').write_text(json.dumps({'id': 'deadbeef' * 4}))
    reports = sync(['orphan'], root=root)
    got = by_project(reports)
    assert got['orphan']['identity'] == 'skipped' and got['orphan']['database'] == 'attention'
    assert not (tmp_path / 'state').exists()


def test_broken_frontmatter_and_name_mismatch_are_attention(root, tmp_path):
    broken = tmp_path / 'broken'
    broken.mkdir()
    (broken / 'AGENTS.md').write_text('# no frontmatter\n')
    register(root, 'broken', broken)
    other = agents_only(tmp_path, 'other')
    register(root, 'alias', other)
    got = by_project(sync(['broken', 'alias'], root=root))
    assert got['broken'] == {'agents_md': 'attention'}
    assert got['alias'] == {'agents_md': 'attention'}
    assert not (other / '.devflow').exists()


def test_names_are_required_and_must_be_registered(root, three):
    with pytest.raises(WorkflowError):
        sync(root=root)
    with pytest.raises(WorkflowError):
        sync(['nobody'], root=root)
