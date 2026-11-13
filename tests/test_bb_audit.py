import pytest

from devflow import workflow
from devflow.documents import WorkflowError

from test_pi import approve_plan, fake_pi, proj  # noqa: F401


def blocked_step(proj):
    rev = approve_plan(proj)
    run = workflow.start(proj['ctx'], proj['db'], 'x', 'one', rev)['run_id']
    workflow.interrupt(proj['db'], run, 'смоук без тенанта')
    return run


def test_accept_step_closes_blocked_attempt_by_user_decision(proj):
    run = blocked_step(proj)
    out = workflow.accept_step(proj['ctx'], proj['db'], 'x', 'смоук на проде')
    assert out['accepted'] == 'one' and out['state'] == 'ready' and out['step'] == 'two'
    last = proj['db'].execute("SELECT action, data FROM events ORDER BY rowid DESC LIMIT 1").fetchone()
    assert last['action'] == 'accept_step' and run in last['data'] and 'смоук на проде' in last['data']


def test_accept_step_refuses_without_blocked_attempt_or_reason(proj):
    approve_plan(proj)
    with pytest.raises(WorkflowError, match='no blocked'):
        workflow.accept_step(proj['ctx'], proj['db'], 'x', 'решение')
    with pytest.raises(WorkflowError, match='--reason'):
        workflow.accept_step(proj['ctx'], proj['db'], 'x', '  ')


def test_plain_repo_keeps_one_running_step(proj, tmp_path):
    rev = approve_plan(proj)
    (proj['cwd'] / '.git').mkdir()
    proj['db'].execute("INSERT INTO runs(id,slug,step_id,step_revision,plan_revision,research_revision,status) "
                       "VALUES ('r','other-1','s','a','b','c','running')")
    with pytest.raises(WorkflowError, match='Another step'):
        workflow.start(proj['ctx'], proj['db'], 'x', 'one', rev)


def test_metarepo_allows_disjoint_repos(proj, monkeypatch):
    rev = approve_plan(proj)
    repos = {'x': {'/a'}, 'other-1': {'/b'}}
    monkeypatch.setattr(workflow, '_task_repos', lambda ctx, slug: repos[slug])
    proj['db'].execute("INSERT INTO runs(id,slug,step_id,step_revision,plan_revision,research_revision,status) "
                       "VALUES ('r','other-1','s','a','b','c','running')")
    assert workflow.start(proj['ctx'], proj['db'], 'x', 'one', rev)['step'] == 'one'


@pytest.mark.parametrize('theirs', [{'/a'}, set()])
def test_metarepo_blocks_shared_or_unknown_repos(proj, monkeypatch, theirs):
    rev = approve_plan(proj)
    repos = {'x': {'/a'}, 'other-1': theirs}
    monkeypatch.setattr(workflow, '_task_repos', lambda ctx, slug: repos[slug])
    proj['db'].execute("INSERT INTO runs(id,slug,step_id,step_revision,plan_revision,research_revision,status) "
                       "VALUES ('r','other-1','s','a','b','c','running')")
    with pytest.raises(WorkflowError, match='Another step'):
        workflow.start(proj['ctx'], proj['db'], 'x', 'one', rev)
