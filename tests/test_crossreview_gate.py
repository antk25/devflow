from devflow import cli, workflow

from test_bb_audit import blocked_step
from test_host_parity import result
from test_pi import approve_plan, proj, shared_rules  # noqa: F401


def done(p, step, rev):
    run = workflow.start(p['ctx'], p['db'], 'x', step, rev)['run_id']
    result(p, run, 'done')


def finished(p):
    rev = approve_plan(p)
    done(p, 'one', rev)
    done(p, 'two', rev)
    return rev


def route(p):
    return workflow.route(p['ctx'], p['db'], 'x')


def test_all_done_without_note_waits_for_crossreview(proj):
    finished(proj)
    out = route(proj)
    assert out['state'] == 'crossreview_required' and out['phase'] is None
    assert out['crossreview_note'] == str(proj['vault'] / 'notes' / 'x-cross-review.md')
    assert 'crossreview' not in out


def test_exact_note_completes(proj):
    finished(proj)
    (proj['vault'] / 'notes').mkdir()
    (proj['vault'] / 'notes/x-cross-review.md').write_text('# Ревью\n')
    out = route(proj)
    assert out['state'] == 'completed' and out['crossreview'] == 'note'


def test_similar_names_do_not_count(proj):
    finished(proj)
    (proj['vault'] / 'notes').mkdir()
    (proj['vault'] / 'notes/X-cross-review.md').write_text('#\n')
    (proj['vault'] / 'notes/x-cross-review-2.md').write_text('#\n')
    assert route(proj)['state'] == 'crossreview_required'


def test_close_without_gate_mark_is_legacy(proj):
    finished(proj)
    proj['db'].execute("UPDATE events SET data=json_remove(data,'$.crossreview_gate') WHERE action='finish'")
    out = route(proj)
    assert out['state'] == 'completed' and out['crossreview'] == 'legacy'


def test_imported_steps_without_events_are_legacy(proj):
    rev = approve_plan(proj)
    for s in workflow.plan_steps(workflow.task_docs(proj['ctx'], 'x')[2]):
        proj['db'].execute('INSERT INTO steps VALUES (?,?,?,?,?)', ('x', s['id'], s['revision'], 'done', 'legacy-import'))
    out = route(proj)
    assert rev and out['state'] == 'completed' and out['crossreview'] == 'legacy'


def test_accept_step_on_last_step_waits_for_crossreview(proj):
    rev = approve_plan(proj)
    done(proj, 'one', rev)
    run = workflow.start(proj['ctx'], proj['db'], 'x', 'two', rev)['run_id']
    workflow.interrupt(proj['db'], run, 'смоук без тенанта')
    out = workflow.accept_step(proj['ctx'], proj['db'], 'x', 'смоук на проде')
    assert out['state'] == 'crossreview_required' and out['accepted'] == 'two'
    last = proj['db'].execute("SELECT json_extract(data,'$.crossreview_gate') AS g FROM events "
                              "WHERE action='accept_step'").fetchone()
    assert last['g'] == 1


def test_blocked_step_helper_still_ready(proj):
    blocked_step(proj)
    assert workflow.accept_step(proj['ctx'], proj['db'], 'x', 'да')['state'] == 'ready'


def test_active_lists_task_waiting_for_crossreview(proj):
    finished(proj)
    plans = cli.active(proj['ctx'], proj['db'])['plans']
    assert [(t['name'], t['status']) for t in plans] == [('x', 'crossreview_required')]
