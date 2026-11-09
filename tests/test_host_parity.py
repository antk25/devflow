"""Общее состояние хостов; внешние исполнители заменены в test_pi."""
import subprocess
import pytest

from devflow import documents, workflow
from devflow.documents import WorkflowError
from test_pi import approve_plan, proj, shared_rules  # noqa: F401


def result(p, run, status):
    path = p['vault'] / 'changelog' / f'{run}.md'
    path.write_text(f'<!-- devflow-run: {run} -->\n**Status:** {status}\n')
    return workflow.finish(p['ctx'], p['db'], run, status, path, 'учебная проверка')


@pytest.mark.parametrize('status', ['partial', 'blocked'])
def test_cross_host_recovery_and_dependencies(proj, status):
    subprocess.run(['git', 'init', '-q', str(proj['cwd'])], check=True)
    rev = approve_plan(proj)
    ctx, db = proj['ctx'], proj['db']
    with pytest.raises(WorkflowError, match='frontier'):
        workflow.start(ctx, db, 'x', 'two', rev)
    run = workflow.start(ctx, db, 'x', 'one', rev)['run_id']
    with pytest.raises(WorkflowError):
        workflow.resume(ctx, db, 'x', 'другой хост')
    result(proj, run, status)
    assert workflow.resume(ctx, db, 'x', 'другой хост')['state'] == 'ready'
    retry = workflow.start(ctx, db, 'x', 'one', rev)['run_id']
    workflow.interrupt(db, retry, 'смена хоста')
    workflow.resume(ctx, db, 'x', 'явное восстановление')
    done = workflow.start(ctx, db, 'x', 'one', rev)['run_id']
    result(proj, done, 'done')
    assert workflow.route(ctx, db, 'x')['frontier'] == ['two']
    out = workflow.reopen(ctx, db, 'x', 'one', rev, 'повторная проверка')
    assert out['reopened'] == ['one', 'two']
    assert workflow.route(ctx, db, 'x')['state'] == 'approval_required'
    assert db.execute('SELECT count(*) FROM runs').fetchone()[0] == 3


def test_shortened_plan_preserves_completed_definition_and_history(proj):
    rev = approve_plan(proj)
    ctx, db = proj['ctx'], proj['db']
    run = workflow.start(ctx, db, 'x', 'one', rev)['run_id']
    result(proj, run, 'done')
    plan = proj['vault'] / 'plans/x.md'
    original = plan.read_text()
    plan.write_text(original + '\n## Risks\nВспомогательные возможности отложены.\n')
    current = workflow.route(ctx, db, 'x')
    assert current['state'] == 'approval_required'
    assert current['revision'] != rev
    with pytest.raises(WorkflowError):
        workflow.approve(ctx, db, 'x', 'plan', rev)
    workflow.approve(ctx, db, 'x', 'plan', current['revision'])
    assert workflow.route(ctx, db, 'x')['frontier'] == ['two']
    assert db.execute('SELECT status FROM runs WHERE id=?', (run,)).fetchone()[0] == 'done'
    assert documents.document(plan)['revision'] == current['revision']
