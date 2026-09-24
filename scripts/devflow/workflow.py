"""Deterministic routing and guarded state transitions."""
import json
import os
import re
import uuid
from pathlib import Path

import yaml

from . import jev
from .documents import (WorkflowError, artifact, digest, document, headings, overall_criteria, plan_steps,
                        requirement, resolve_slug, section_items, step_criteria)
from .storage import approved, atomic_write, event, now, remember, transaction


MARKER = '<!-- devflow-run: {} -->'
LIMIT = 60000
PLAN_LIMIT = 60000


def run_section(raw, run_id):
    marker = MARKER.format(run_id)
    if raw.count(marker) != 1:
        return None
    return raw.split(marker, 1)[1].split('<!-- devflow-run:', 1)[0]


def task_docs(ctx, query):
    slug = resolve_slug(ctx['vault'], query)
    return slug, artifact(ctx['vault'], 'research', slug), artifact(ctx['vault'], 'plans', slug)


def pending_path(ctx, slug):
    return ctx['cwd'] / '.devflow' / 'migrations' / (slug + '.json')


def route(ctx, db, query):
    slug, research, plan = task_docs(ctx, query)
    result = {'slug': slug, 'state': 'research', 'phase': 'research',
              'research_revision': research['revision'] if research else None,
              'plan_revision': plan['revision'] if plan else None,
              'research_path': research['path'] if research else None,
              'plan_path': plan['path'] if plan else None,
              'research_approved': approved(db, slug, 'research', research),
              'plan_approved': approved(db, slug, 'plan', plan)}
    if pending_path(ctx, slug).exists():
        return dict(result, state='migration_pending', phase=None)
    running = db.execute("SELECT * FROM runs WHERE slug=? AND status='running'", (slug,)).fetchone()
    if running:
        return dict(result, state='running', phase='implement', run_id=running['id'], step=running['step_id'],
                    revision=running['plan_revision'], research_revision=running['research_revision'],
                    documents_changed=not (plan and research and plan['revision'] == running['plan_revision']
                                           and research['revision'] == running['research_revision']))
    stopped = db.execute("SELECT * FROM runs WHERE slug=? AND status IN ('blocked','partial') ORDER BY rowid DESC LIMIT 1", (slug,)).fetchone()
    if stopped:
        return dict(result, state='blocked', phase=None, run_id=stopped['id'], reason=stopped['reason'])
    if plan and 'schema' not in plan['meta']:
        return dict(result, state='migration_required', phase=None, revision=plan['revision'])
    steps = plan_steps(plan) if plan else []
    if not research:
        if plan:
            raise WorkflowError('Plan has no research artifact; restore or create research before approval')
        logs = list((ctx['vault'] / 'changelog').glob('*-' + slug + '.md'))
        if logs:
            return dict(result, state='legacy_review', phase=None, reason='Changelog alone cannot prove completion')
        tz = artifact(ctx['vault'], 'tz', slug)
        return dict(result, source='tz' if tz else 'new', artifact=tz['path'] if tz else None)
    if not approved(db, slug, 'research', research):
        return dict(result, state='approval_required', revision=research['revision'], artifact=research['path'])
    if not plan:
        return dict(result, state='plan', phase='plan', research_revision=research['revision'])
    if plan['meta']['research_revision'] != research['revision']:
        return dict(result, state='plan_outdated', phase='plan', research_revision=research['revision'])
    saved = {s['id']: dict(s) for s in db.execute('SELECT * FROM steps WHERE slug=?', (slug,))}
    changed = [s['id'] for s in steps if s['id'] in saved and saved[s['id']]['status'] == 'done'
               and saved[s['id']]['revision'] != s['revision']]
    removed = sorted(ident for ident, row in saved.items() if row['status'] == 'done' and ident not in {s['id'] for s in steps})
    if changed or removed:
        return dict(result, state='review_required', phase=None, changed_done_steps=changed,
                    removed_done_steps=removed, revision=plan['revision'])
    if not approved(db, slug, 'plan', plan):
        return dict(result, state='approval_required', phase='plan', revision=plan['revision'], artifact=plan['path'])
    done = {s['id'] for s in steps if s['id'] in saved and saved[s['id']]['status'] == 'done'}
    frontier = [s for s in steps if s['id'] not in done and set(s['blocked_by']) <= done]
    state = 'completed' if len(done) == len(steps) else 'ready' if frontier else 'blocked'
    return dict(result, state=state, phase='implement' if frontier else None,
                revision=plan['revision'], research_revision=research['revision'],
                total=len(steps), done=sorted(done), frontier=[s['id'] for s in frontier],
                step=frontier[0]['id'] if frontier else None, n=frontier[0]['n'] if frontier else None)


def approve(ctx, db, query, phase, revision):
    with transaction(db):
        current = route(ctx, db, query)
        if current['state'] != 'approval_required' or current['phase'] != phase:
            slug, research, plan = task_docs(ctx, query)
            doc = research if phase == 'research' else plan
            if doc and doc['revision'] == revision and approved(db, slug, phase, doc):
                return {'slug': slug, 'approved': phase, 'revision': revision, 'unchanged': True}
            raise WorkflowError('This phase is not awaiting approval: ' + current['state'])
        if revision != current['revision']:
            raise WorkflowError('Artifact changed since it was shown; show it again before approval')
        slug, research, plan = task_docs(ctx, query)
        doc = research if phase == 'research' else plan
        if doc['revision'] != revision:
            raise WorkflowError('Artifact changed during approval')
        remember(db, slug, phase, doc)
        db.execute('INSERT OR IGNORE INTO approvals VALUES (?,?,?,?)', (slug, phase, revision, now()))
        event(db, 'approve', slug, phase=phase, revision=revision)
    return {'slug': slug, 'approved': phase, 'revision': revision}


def start(ctx, db, query, step_id, revision):
    with transaction(db):
        current = route(ctx, db, query)
        if current['state'] != 'ready' or current['revision'] != revision:
            raise WorkflowError('Task is not ready at the requested plan revision: ' + current['state'])
        if step_id not in current['frontier']:
            raise WorkflowError('Step is not on the frontier')
        if db.execute("SELECT 1 FROM runs WHERE status='running'").fetchone():
            raise WorkflowError('Another step is running in this project; finish or interrupt it first')
        slug, research, plan = task_docs(ctx, query)
        if plan['revision'] != revision or research['revision'] != current['research_revision']:
            raise WorkflowError('Documents changed during start')
        step = next(s for s in plan_steps(plan) if s['id'] == step_id)
        run = str(uuid.uuid4())
        db.execute('INSERT INTO runs(id,slug,step_id,step_revision,plan_revision,research_revision,status) VALUES (?,?,?,?,?,?,?)',
                   (run, slug, step_id, step['revision'], revision, research['revision'], 'running'))
        event(db, 'start', slug, run_id=run, step=step_id, revision=revision)
    return {'run_id': run, 'slug': slug, 'step': step_id, 'revision': revision}


def finish(ctx, db, run_id, status, changelog, reason):
    with transaction(db):
        run = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not run:
            raise WorkflowError('Unknown run ID')
        path = Path(changelog).resolve()
        if not path.is_relative_to((ctx['vault'] / 'changelog').resolve()):
            raise WorkflowError('Changelog must be inside this project vault/changelog')
        doc = document(path)
        section = run_section(doc['raw'], run_id)
        if section is None:
            raise WorkflowError('Changelog needs exactly one run marker: ' + MARKER.format(run_id))
        if not re.search(r'^\*\*Status:\*\* ' + status + r'\s*$', section, re.M):
            raise WorkflowError('Run section needs **Status:** ' + status)
        # Hash only this run section: later appends must not invalidate an idempotent finish.
        evidence = digest(section.strip())
        if run['status'] == status and run['changelog'] == str(path) and run['changelog_revision'] == evidence:
            return {'run_id': run_id, 'status': status, 'unchanged': True}
        if run['status'] != 'running':
            raise WorkflowError('Run is not running; its recorded result cannot be overwritten')
        if status == 'done':
            slug, research, plan = task_docs(ctx, run['slug'])
            if not plan or not research or plan['revision'] != run['plan_revision'] or research['revision'] != run['research_revision']:
                raise WorkflowError('Documents changed during execution; finish as blocked and review the plan')
            if not approved(db, slug, 'plan', plan) or not approved(db, slug, 'research', research):
                raise WorkflowError('Current documents are not approved')
            db.execute('INSERT INTO steps VALUES (?,?,?,?,?) ON CONFLICT(slug,id) DO UPDATE SET revision=excluded.revision,status=excluded.status,source=excluded.source',
                       (slug, run['step_id'], run['step_revision'], 'done', run_id))
        elif not reason:
            raise WorkflowError('Blocked/partial runs need --reason')
        remember(db, run['slug'], 'changelog', doc)
        db.execute('UPDATE runs SET status=?,reason=?,changelog=?,changelog_revision=? WHERE id=?',
                   (status, reason, str(path), evidence, run_id))
        event(db, 'finish', run['slug'], run_id=run_id, status=status, reason=reason, evidence=evidence)
    return {'run_id': run_id, 'status': status}


def interrupt(db, run_id, reason):
    with transaction(db):
        run = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if not run or run['status'] != 'running':
            raise WorkflowError('Run is not running')
        db.execute("UPDATE runs SET status='blocked',reason=? WHERE id=?", (reason, run_id))
        event(db, 'interrupt', run['slug'], run_id=run_id, reason=reason)
    return {'run_id': run_id, 'status': 'blocked'}


def resume(ctx, db, query, reason):
    slug = resolve_slug(ctx['vault'], query)
    with transaction(db):
        if db.execute("SELECT 1 FROM runs WHERE slug=? AND status='running'", (slug,)).fetchone():
            raise WorkflowError('Inspect and interrupt the running attempt first')
        changed = db.execute("UPDATE runs SET status='resumed' WHERE slug=? AND status IN ('blocked','partial')", (slug,)).rowcount
        if not changed:
            raise WorkflowError('Task has no blocked/partial attempts')
        event(db, 'resume', slug, reason=reason)
    return route(ctx, db, slug)


def reopen(ctx, db, query, step_id, revision, reason):
    with transaction(db):
        slug, _, plan = task_docs(ctx, query)
        if not plan or plan['revision'] != revision:
            raise WorkflowError('Plan revision changed')
        steps = plan_steps(plan)
        if step_id not in {s['id'] for s in steps}:
            raise WorkflowError('Unknown step ID')
        if db.execute("SELECT 1 FROM runs WHERE slug=? AND status='running'", (slug,)).fetchone():
            raise WorkflowError('Cannot reopen during execution')
        affected = {step_id}
        while True:
            expanded = affected | {s['id'] for s in steps if set(s['blocked_by']) & affected}
            if expanded == affected:
                break
            affected = expanded
        for ident in affected:
            db.execute("UPDATE steps SET status='open' WHERE slug=? AND id=?", (slug, ident))
        db.execute("DELETE FROM approvals WHERE slug=? AND phase='plan'", (slug,))
        event(db, 'reopen', slug, steps=sorted(affected), reason=reason)
    return {'slug': slug, 'reopened': sorted(affected), 'approval_required': True}


def migration_preview(ctx, query):
    slug, research, plan = task_docs(ctx, query)
    if not plan:
        raise WorkflowError('No plan to migrate')
    if 'schema' in plan['meta']:
        raise WorkflowError('Plan already declares a schema; legacy migration will not overwrite it')
    if not research:
        raise WorkflowError('Restore or write research before migration; approvals cannot be inferred')
    old = plan['meta'].get('steps')
    if not old:
        raise WorkflowError('Legacy plan without step statuses requires manual reconciliation; do not infer progress from changelog')
    if not isinstance(old, list):
        raise WorkflowError('Legacy steps must be a list')
    ids, imported, steps = {}, [], []
    for s in old:
        if not isinstance(s, dict) or type(s.get('n')) is not int or s['n'] < 1 or s['n'] in ids:
            raise WorkflowError('Invalid legacy step numbers')
        if s.get('status') not in ('open', 'done'):
            raise WorkflowError('Unknown legacy status; reconcile manually')
        ids[s['n']] = f"step-{s['n']}"
        if s['status'] == 'done':
            imported.append(ids[s['n']])
    for s in old:
        deps = s.get('blocked_by', [])
        if not isinstance(deps, list) or any(type(d) is not int or d not in ids for d in deps):
            raise WorkflowError('Unknown legacy dependency')
        steps.append({'id': ids[s['n']], 'n': s['n'], 'blocked_by': [ids[d] for d in deps]})
    done_ids = set(imported)
    for step in steps:
        if step['id'] in done_ids and not set(step['blocked_by']) <= done_ids:
            raise WorkflowError('Legacy completed step has unfinished dependencies; reconcile manually')
    body = plan['body']
    found = set()
    legacy_headings, in_steps = [], False
    for heading in headings(body):
        if heading[0] <= 2:
            in_steps = heading[0] == 2 and heading[1] == 'Steps'
        if in_steps:
            legacy_headings.append(heading)
    for level, title, start_pos in reversed(legacy_headings):
        m = re.match(r'(\d+)\.\s+(.*)', title)
        if level == 3 and m:
            n = int(m[1])
            if n not in ids or n in found:
                raise WorkflowError('Legacy headings do not match step numbers')
            found.add(n)
            end = body.find('\n', start_pos)
            end = len(body) if end < 0 else end
            body = body[:start_pos] + f'### {ids[n]}: {m[2]}' + body[end:]
    if found != set(ids):
        raise WorkflowError('Legacy headings do not match step numbers')
    meta = dict(plan['meta'], schema=1, research_revision=research['revision'], steps=steps)
    raw = '---\n' + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + '---\n' + body
    converted = {'meta': meta, 'body': body}
    validated = plan_steps(converted)
    return {'slug': slug, 'old_revision': plan['revision'], 'new_revision': digest(raw),
            'path': plan['path'], 'research_revision': research['revision'], 'old_content': plan['raw'],
            'new_content': raw, 'imported_done': imported, 'steps': validated,
            'approvals': 'none; show and approve research and plan after import'}


def migrate(ctx, db, query, apply_revision=None):
    slug = resolve_slug(ctx['vault'], query)
    pending = pending_path(ctx, slug)
    preview = json.loads(pending.read_text()) if pending.exists() else migration_preview(ctx, slug)
    if not apply_revision:
        return preview
    if preview['old_revision'] != apply_revision:
        raise WorkflowError('Migration preview revision changed')
    with transaction(db):
        if db.execute('SELECT 1 FROM runs WHERE slug=?', (slug,)).fetchone():
            raise WorkflowError('Cannot import over existing execution history')
        done = db.execute('SELECT * FROM migrations WHERE slug=?', (slug,)).fetchone()
        if done and done['new_revision'] != preview['new_revision']:
            raise WorkflowError('A different migration was already applied')
        current = document(Path(preview['path']))
        if current['revision'] not in (preview['old_revision'], preview['new_revision']):
            raise WorkflowError('Plan changed; reconcile the pending migration manually')
        research = artifact(ctx['vault'], 'research', slug)
        if not research or research['revision'] != preview['research_revision']:
            raise WorkflowError('Research changed since migration preview')
        if not pending.exists():
            atomic_write(pending, json.dumps(preview, ensure_ascii=False, indent=2) + '\n')
        backup = Path(preview['path'] + '.pre-devflow.bak')
        if backup.exists() and backup.read_text() != preview['old_content']:
            raise WorkflowError('Migration backup already exists with different contents')
        atomic_write(backup, preview['old_content'])
        atomic_write(Path(preview['path']), preview['new_content'])
        if not done:
            for step in preview['steps']:
                if step['id'] in preview['imported_done']:
                    db.execute('INSERT INTO steps VALUES (?,?,?,?,?)',
                               (slug, step['id'], step['revision'], 'done', 'legacy-import'))
            db.execute('INSERT INTO migrations VALUES (?,?,?)',
                       (slug, preview['old_revision'], preview['new_revision']))
            event(db, 'migrate', slug, imported_done=preview['imported_done'], revision=preview['new_revision'])
    pending.unlink()
    return {'slug': slug, 'migrated': True, 'imported_done': preview['imported_done'], 'approvals': 'none'}


def check(ctx, db, query, run_id, all_, plan_=False):
    slug = resolve_slug(ctx['vault'], query)
    if plan_:
        return check_plan(ctx, db, slug)
    threshold = float(os.environ.get('DEVFLOW_JEV_THRESHOLD', '0.7'))
    result = {'slug': slug, 'run_id': run_id, 'threshold': threshold, 'model': None, 'criteria': []}
    reason = _check(ctx, db, slug, run_id, all_, threshold, result)
    result = dict(result, status='skipped', reason=reason) if reason else dict(result, status='ok')
    with transaction(db):
        event(db, 'check', slug, run_id=run_id, all=all_, status=result['status'], reason=reason,
              model=result['model'], threshold=threshold,
              noul=[c['noul'] for c in result['criteria']], flagged=[c['flagged'] for c in result['criteria']])
    return result


def _check(ctx, db, slug, run_id, all_, threshold, result):
    if document(ctx['cwd'] / 'AGENTS.md')['meta'].get('jev') is not True:
        return 'jev не включён в AGENTS.md'
    if not os.environ.get('OPENROUTER_API_KEY'):
        return 'OPENROUTER_API_KEY не задан'
    plan = artifact(ctx['vault'], 'plans', slug)
    if not plan:
        return 'нет плана'
    logs = list((ctx['vault'] / 'changelog').glob('*-' + slug + '.md'))
    if len(logs) != 1:
        return 'нужен ровно один changelog, найдено: ' + str(len(logs))
    raw = logs[0].read_text(encoding='utf-8')
    title = next((l[2:].strip() for l in plan['body'].splitlines() if l.startswith('# ')), slug)
    if all_:
        criteria, chunks = overall_criteria(plan['body']), [raw]
        if len(raw) > LIMIT:
            chunks = raw.split('<!-- devflow-run:')[1:] or [raw]
            if any(len(c) > LIMIT for c in chunks):
                return 'секция changelog больше лимита ' + str(LIMIT) + ' символов'
    else:
        run = db.execute('SELECT * FROM runs WHERE id=? AND slug=?', (run_id, slug)).fetchone()
        if not run:
            return 'прогон не найден'
        step = next((s for s in plan_steps(plan) if s['id'] == run['step_id']), None)
        section = run_section(raw, run_id)
        if not step or section is None:
            return 'нет шага или секции прогона в changelog'
        criteria, chunks = step_criteria(step['text']), [section]
        if len(section) > LIMIT:
            return 'секция прогона больше лимита ' + str(LIMIT) + ' символов'
    if not criteria:
        return 'в плане нет критериев'
    items, model = [{'criterion': c, 'noul': None, 'choice': None, 'flagged': None} for c in criteria], None
    for chunk in chunks:
        out = jev.decide({'task': title, 'changelog': jev.mask(chunk.strip())}, jev.questions(criteria))
        if 'error' in out:
            return out['error']
        model = out['model']
        for n, item in enumerate(items):
            noul = (out['answers'].get(f'ev_{n}') or {}).get('noul')
            if not isinstance(noul, (int, float)):
                return 'в ответе нет noul для ev_' + str(n)
            if item['noul'] is None or noul > item['noul']:
                item['noul'] = noul
                item['choice'] = (out['answers'].get(f'st_{n}') or {}).get('choice')
    for item in items:
        item['flagged'] = jev.flag(item['noul'], threshold)
    result.update(criteria=items, model=model)
    return None


def check_plan(ctx, db, slug):
    threshold = float(os.environ.get('DEVFLOW_JEV_PLAN_THRESHOLD', '0.95'))
    result = {'slug': slug, 'kind': 'plan', 'threshold': threshold, 'model': None, 'requirements': []}
    reason = _check_plan(ctx, slug, threshold, result)
    result = dict(result, status='skipped', reason=reason) if reason else dict(result, status='ok', reason=None)
    with transaction(db):
        event(db, 'check', slug, kind='plan', status=result['status'], reason=reason, model=result['model'],
              threshold=threshold, noul=[r['noul'] for r in result['requirements']],
              flagged=[r['flagged'] for r in result['requirements']])
    return result


def _check_plan(ctx, slug, threshold, result):
    if document(ctx['cwd'] / 'AGENTS.md')['meta'].get('jev') is not True:
        return 'jev не включён в AGENTS.md'
    if not os.environ.get('OPENROUTER_API_KEY'):
        return 'OPENROUTER_API_KEY не задан'
    research = artifact(ctx['vault'], 'research', slug)
    if not research:
        return 'нет требований'
    reqs = [r for r in map(requirement, section_items(research['body'], 'Requirements'))
            if r['text'] and not r['wish'] and r['text'].lower().rstrip('.') != 'требований нет']
    if not reqs:
        return 'нет требований'
    plan = artifact(ctx['vault'], 'plans', slug)
    if not plan:
        return 'нет плана'
    texts = [r['text'] for r in reqs]
    state = {'ticket': jev.mask('\n'.join(f"- {r['text']} ({r['source']})" if r['source'] else '- ' + r['text']
                                           for r in reqs)),
             'plan': jev.mask(plan['raw'])}
    questions = jev.plan_questions(texts)
    size = len(json.dumps({'state': state, 'questions': questions}, ensure_ascii=False))
    if size > PLAN_LIMIT:
        return f'план больше лимита: {size} символов'
    out = jev.decide(state, questions)
    if 'error' in out:
        return out['error']
    items = []
    for n, r in enumerate(reqs, 1):
        noul = (out['answers'].get(f'addr_{n}') or {}).get('noul')
        if not isinstance(noul, (int, float)):
            return f'в ответе нет noul для addr_{n}'
        items.append({'n': n, 'text': r['text'], 'source': r['source'], 'noul': noul,
                      'choice': (out['answers'].get(f'cov_{n}') or {}).get('choice'),
                      'flagged': jev.flag(noul, threshold)})
    result.update(requirements=items, model=out['model'])
    return None
