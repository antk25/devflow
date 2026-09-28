import pytest

from devflow import documents, policy, workflow
from devflow.documents import WorkflowError, context
from devflow.storage import connect

EXAMPLE = documents.Path(__file__).resolve().parents[1] / 'model-policy.example.json'


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv('DEVFLOW_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('DEVFLOW_MODEL_POLICY', str(EXAMPLE))
    vault, cwd = tmp_path / 'vault', tmp_path / 'proj'
    for d in ('plans', 'research', 'changelog'):
        (vault / d).mkdir(parents=True)
    cwd.mkdir()
    (cwd / 'AGENTS.md').write_text(f'---\nproject: p\nvault: {vault}\n---\n')
    (vault / 'research/x.md').write_text('# r\n')
    ctx = context(cwd)
    db = connect(ctx, create=True)
    workflow.approve(ctx, db, 'x', 'research', documents.document(vault / 'research/x.md')['revision'])
    yield {'ctx': ctx, 'db': db}
    db.close()


def events(db, slug):
    import json
    return [json.loads(r['data']) for r in db.execute("SELECT data FROM events WHERE slug=? AND action='complexity' ORDER BY id", (slug,))]


def test_show_without_events(proj):
    assert workflow.complexity(proj['ctx'], proj['db'], 'x') == {'slug': 'x', 'user': None, 'jev': None}
    assert workflow.route(proj['ctx'], proj['db'], 'x')['complexity'] is None


def test_set_high_records_event_and_route_uses_it(proj):
    out = workflow.complexity(proj['ctx'], proj['db'], 'x', 'high', 'research')
    assert out['user']['value'] == 'high' and out['user']['gate'] == 'research' and out['user']['at']
    assert out['jev'] is None
    assert events(proj['db'], 'x') == [{'value': 'high', 'gate': 'research', 'source': 'user', 'applied': True}]
    route = workflow.route(proj['ctx'], proj['db'], 'x')
    assert route['state'] == 'plan'
    assert route['complexity']['value'] == 'high' and route['complexity']['gate'] == 'research'
    assert route['launch']['claude']['effort'] == 'high'


def test_second_set_appends_event(proj):
    workflow.complexity(proj['ctx'], proj['db'], 'x', 'high', 'research')
    out = workflow.complexity(proj['ctx'], proj['db'], 'x', 'medium', 'plan')
    assert out['user']['value'] == 'medium' and out['user']['gate'] == 'plan'
    assert [e['value'] for e in events(proj['db'], 'x')] == ['high', 'medium']
    assert workflow.route(proj['ctx'], proj['db'], 'x')['launch']['claude']['effort'] == 'medium'


def test_route_ignores_non_user_events(proj):
    from devflow.storage import event, transaction
    with transaction(proj['db']):
        event(proj['db'], 'complexity', 'x', value='high', gate='research', source='jev', applied=False)
    assert workflow.route(proj['ctx'], proj['db'], 'x')['complexity'] is None
    assert workflow.complexity(proj['ctx'], proj['db'], 'x')['user'] is None


def test_set_validates_value_and_gate(proj):
    with pytest.raises(WorkflowError, match='Complexity'):
        workflow.complexity(proj['ctx'], proj['db'], 'x', 'huge', 'research')
    with pytest.raises(WorkflowError, match='--gate'):
        workflow.complexity(proj['ctx'], proj['db'], 'x', 'high', None)
    assert events(proj['db'], 'x') == []
