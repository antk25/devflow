"""Оценка сложности задачи: выбор пользователя, тень Jev и факты по задаче."""
import json
import os
import time

from . import jev
from .documents import WorkflowError, artifact, document, plan_steps, resolve_slug, section
from .storage import event, transaction


COMPLEXITY = ('high', 'medium', 'low')
GATES = ('research', 'plan', 'backfill')


def user_complexity(db, slug):
    """Last `complexity` event set by the user: {value, gate, at} or None."""
    for row in db.execute("SELECT at, data FROM events WHERE slug=? AND action='complexity' ORDER BY id DESC", (slug,)):
        data = json.loads(row['data'])
        if data.get('source') == 'user':
            return {'value': data['value'], 'gate': data.get('gate'), 'at': row['at']}
    return None


def jev_complexity(db, slug):
    """Last shadow `complexity` event from Jev, or None."""
    for row in db.execute("SELECT at, data FROM events WHERE slug=? AND action='complexity' ORDER BY id DESC", (slug,)):
        data = json.loads(row['data'])
        if data.get('source') == 'jev':
            return dict(data, at=row['at'])
    return None


def complexity(ctx, db, query, value=None, gate=None, shadow=True):
    slug = resolve_slug(ctx['vault'], query)
    if value:
        if value not in COMPLEXITY:
            raise WorkflowError('Complexity must be one of: ' + ', '.join(COMPLEXITY))
        if gate not in GATES:
            raise WorkflowError('--gate must be one of: ' + ', '.join(GATES))
        with transaction(db):
            event(db, 'complexity', slug, value=value, gate=gate, source='user', applied=True)
        if shadow:
            shadow_complexity(ctx, db, slug, gate)
    elif gate == 'backfill' and shadow:
        # Backfill: only Jev's shadow opinion; the user's value stays untouched until a later --set.
        shadow_complexity(ctx, db, slug, gate)
    return {'slug': slug, 'user': user_complexity(db, slug), 'jev': jev_complexity(db, slug),
            'facts': complexity_facts(ctx, db, slug)}


def complexity_facts(ctx, db, slug):
    """What actually happened to the task: plan size, runs and their outcomes, artifact revisions."""
    plan = artifact(ctx['vault'], 'plans', slug)
    try:
        steps = len(plan_steps(plan)) if plan else 0
    except WorkflowError:
        steps = len(plan['meta'].get('steps') or []) if isinstance(plan['meta'].get('steps'), list) else 0
    statuses = {}
    for row in db.execute('SELECT status, COUNT(*) AS n FROM runs WHERE slug=? GROUP BY status ORDER BY status', (slug,)):
        statuses[row['status']] = row['n']
    def revisions(phase):
        return db.execute('SELECT COUNT(*) AS n FROM artifacts WHERE slug=? AND phase=?', (slug, phase)).fetchone()['n']
    return {'steps': steps, 'runs': sum(statuses.values()), 'statuses': statuses,
            'research_revisions': revisions('research'), 'plan_revisions': revisions('plan')}


def shadow_complexity(ctx, db, slug, gate):
    """Ask Jev what it would answer and record it as `source=jev, applied=false`; never raises, never applied."""
    data = {'value': None, 'gate': gate, 'source': 'jev', 'applied': False, 'choice': None, 'confidence': None,
            'noul': {'unclear': None, 'wide': None}, 'model': None, 'input_chars': 0, 'sources': [],
            'latency_ms': None, 'error': None}
    data['error'] = _shadow_complexity(ctx, slug, data)
    with transaction(db):
        event(db, 'complexity', slug, **data)
    return data


def _shadow_complexity(ctx, slug, data):
    if document(ctx['cwd'] / 'AGENTS.md')['meta'].get('jev') is not True:
        return 'jev не включён в AGENTS.md'
    if not os.environ.get('OPENROUTER_API_KEY'):
        return 'OPENROUTER_API_KEY не задан'
    tz = artifact(ctx['vault'], 'tz', slug)
    research = artifact(ctx['vault'], 'research', slug)
    state = {'tz': jev.mask(tz['body'].strip()) if tz else '',
             'requirements': jev.mask(section(research['body'], 'Requirements').strip()) if research else ''}
    data['sources'] = [k for k, v in state.items() if v]
    if not data['sources']:
        return 'нет ни ТЗ, ни требований'
    questions = jev.complexity_questions()
    data['input_chars'] = len(json.dumps({'state': state, 'questions': questions}, ensure_ascii=False))
    if data['input_chars'] > jev.INPUT_LIMIT:
        return f"вход больше лимита: {data['input_chars']} символов"
    started = time.monotonic()
    out = jev.decide(state, questions)
    data['latency_ms'] = int((time.monotonic() - started) * 1000)
    if 'error' in out:
        return out['error']
    data['model'] = out['model']
    answers = out['answers']
    for key in ('unclear', 'wide'):
        noul = (answers.get(key) or {}).get('noul')
        if not isinstance(noul, (int, float)):
            return f'в ответе нет noul для {key}'
        data['noul'][key] = noul
    level = answers.get('level') or {}
    choice = level.get('choice')
    if choice not in COMPLEXITY:
        return 'в ответе нет choice для level'
    data['choice'] = data['value'] = choice
    confidence = level.get('confidence')
    if not isinstance(confidence, (int, float)):
        confidence = (level.get('probabilities') or {}).get(choice)
    data['confidence'] = confidence if isinstance(confidence, (int, float)) else None
    return None
