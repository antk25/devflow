import hashlib
import json
from pathlib import Path

import pytest

from devflow.documents import WorkflowError
from devflow.project import init
from devflow.registry import load

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = tmp_path / 'root'
    root.mkdir()
    # The real template points at /mnt/f; tests keep every vault under tmp_path.
    template = (ROOT / 'AGENTS.md.template').read_text().replace('/mnt/f/notes_2/projects/', f'{tmp_path}/vault/')
    (root / 'AGENTS.md.template').write_text(template)
    (root / '.claude/data').mkdir(parents=True)
    (root / '.claude/data/projects.json').write_text(json.dumps({'version': '3.0', 'active': None, 'projects': {}}))
    monkeypatch.setenv('DEVFLOW_STATE_DIR', str(tmp_path / 'state'))
    (tmp_path / 'vault').mkdir()  # the "mounted disk": vault parents must already exist
    return root


@pytest.fixture
def project(tmp_path):
    path = tmp_path / 'proj'
    path.mkdir()
    return path


def draft_for(tmp_path, name):
    vault = tmp_path / 'vault' / name
    draft = tmp_path / f'{name}-draft.md'
    draft.write_text(f'---\nproject: {name}\nvault: {vault}\n---\n\n# {name}\n\n## What\nПроект для теста.\n')
    return draft, vault


def statuses(report):
    return {item['item']: item['status'] for item in report['items']}


def checksums(*roots):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for r in roots for p in Path(r).rglob('*') if p.is_file() and p.suffix != '.lock'}


def test_fresh_directory_creates_everything(root, project, tmp_path):
    draft, vault = draft_for(tmp_path, 'proj')
    report = init(project, None, root, draft)
    assert report['project'] == 'proj'
    assert set(statuses(report).values()) == {'created'}
    assert (project / 'AGENTS.md').read_text() == draft.read_text()
    assert all((vault / d).is_dir() for d in ('tz', 'research', 'plans', 'changelog', 'notes'))
    assert (project / '.devflow/project.json').exists()
    ident = json.loads((project / '.devflow/project.json').read_text())['id']
    assert (tmp_path / 'state' / ident / 'state.sqlite3').exists()
    registry = load(root / '.claude/data/projects.json')
    assert registry['projects']['proj'] == {'path': str(project), 'description': 'Проект для теста.'}
    assert registry['active'] is None


def test_second_run_skips_and_leaves_files_untouched(root, project, tmp_path):
    draft, vault = draft_for(tmp_path, 'proj')
    init(project, None, root, draft)
    before = checksums(project, vault, root, tmp_path / 'state')
    report = init(project, None, root, draft)
    assert set(statuses(report).values()) == {'skipped'}
    assert checksums(project, vault, root, tmp_path / 'state') == before


def test_existing_agents_md_is_preserved_and_names_the_project(root, project, tmp_path):
    vault = tmp_path / 'vault' / 'named'
    text = f'---\nproject: named\nvault: {vault}\n---\n\n# Named\n\n## What\nСтарый файл.\n'
    (project / 'AGENTS.md').write_text(text)
    report = init(project, None, root)
    assert report['project'] == 'named'
    assert statuses(report)['agents_md'] == 'skipped'
    assert (project / 'AGENTS.md').read_text() == text
    assert (vault / 'plans').is_dir()
    assert load(root / '.claude/data/projects.json')['projects']['named']['description'] == 'Старый файл.'
    with pytest.raises(WorkflowError):
        init(project, 'other', root)


def test_dry_run_writes_nothing(root, project, tmp_path):
    draft, vault = draft_for(tmp_path, 'proj')
    before = checksums(tmp_path)
    report = init(project, None, root, draft, dry_run=True)
    assert set(statuses(report).values()) == {'create'}
    assert checksums(tmp_path) == before
    assert not vault.exists() and not (project / 'AGENTS.md').exists()


def test_template_without_draft_substitutes_name(root, project, tmp_path):
    report = init(project, 'proj', root, dry_run=True)
    assert statuses(report)['agents_md'] == 'create'
    init(project, 'proj', root)
    text = (project / 'AGENTS.md').read_text()
    assert 'project: proj\n' in text and '<project-name>' not in text and '<ProjectName>' not in text
    assert (tmp_path / 'vault/proj/plans').is_dir()


def test_name_taken_by_other_path_is_an_error(root, project, tmp_path):
    draft, _ = draft_for(tmp_path, 'proj')
    (root / '.claude/data/projects.json').write_text(json.dumps(
        {'version': '3.0', 'active': None, 'projects': {'proj': {'path': '/elsewhere', 'description': ''}}}))
    with pytest.raises(WorkflowError):
        init(project, None, root, draft)
    assert not (project / 'AGENTS.md').exists()


def test_missing_vault_parent_stops_before_registry(root, project, tmp_path):
    draft = tmp_path / 'draft.md'
    draft.write_text(f'---\nproject: proj\nvault: {tmp_path}/missing/deeper/vault\n---\n\n# proj\n')
    report = init(project, None, root, draft)
    assert [i['item'] for i in report['items']] == ['vault']
    assert statuses(report)['vault'] == 'attention'
    assert load(root / '.claude/data/projects.json')['projects'] == {}
    assert not (project / '.devflow').exists()


def test_git_dir_is_a_warning_not_an_error(root, project, tmp_path):
    draft, _ = draft_for(tmp_path, 'proj')
    (project / '.git').mkdir()
    report = init(project, None, root, draft)
    assert statuses(report)['git'] == 'attention'
    assert statuses(report)['registry'] == 'created'
