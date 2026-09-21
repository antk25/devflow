"""JSON command interface shared by skills, phase agents and startup hooks."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import yaml

from .documents import WorkflowError, artifact, context, document, plan_steps, resolve_slug
from .storage import connect, db_path, identity
from .workflow import approve, finish, interrupt, migrate, reopen, resume, route, start


def active(ctx, db, limit=5):
    result = {'project': ctx['project'], 'vault': str(ctx['vault']), 'tz': [], 'research': [], 'plans': []}
    for folder in ('tz', 'research', 'plans'):
        for path in sorted((ctx['vault'] / folder).glob('*.md'), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                doc = document(path)
                state = route(ctx, db, path.stem) if db else {'state': 'needs_init'}
                if state['state'] == 'completed' or doc['meta'].get('status') in ('archived', 'closed'):
                    continue
                title = next((line[2:] for line in doc['body'].splitlines() if line.startswith('# ')), path.stem)
                result[folder].append({'file': str(path), 'name': path.stem, 'title': title,
                                       'status': state['state'], 'route': state})
            except (WorkflowError, yaml.YAMLError, OSError, ValueError) as exc:
                result[folder].append({'file': str(path), 'name': path.stem, 'status': 'invalid', 'error': str(exc)})
            if len(result[folder]) >= limit:
                break
    return result


def parser():
    p = argparse.ArgumentParser(description='DevFlow state and routing (JSON output)')
    p.add_argument('--cwd', default='.', help='Project root containing AGENTS.md')
    commands = p.add_subparsers(dest='command', required=True)
    a = commands.add_parser('init'); a.add_argument('--fresh-state', action='store_true', help='Explicitly create empty state for an existing identity with a missing database')
    commands.add_parser('context')
    a = commands.add_parser('active'); a.add_argument('--limit', type=int, default=5)
    for name in ('route', 'status', 'validate', 'history'):
        a = commands.add_parser(name); a.add_argument('slug')
    a = commands.add_parser('approve'); a.add_argument('slug'); a.add_argument('phase', choices=['research', 'plan']); a.add_argument('--revision', required=True)
    a = commands.add_parser('start'); a.add_argument('slug'); a.add_argument('--step', required=True); a.add_argument('--revision', required=True)
    a = commands.add_parser('finish'); a.add_argument('run_id'); a.add_argument('--status', choices=['done', 'blocked', 'partial'], required=True); a.add_argument('--changelog', required=True); a.add_argument('--reason')
    a = commands.add_parser('interrupt'); a.add_argument('run_id'); a.add_argument('--reason', required=True)
    a = commands.add_parser('resume'); a.add_argument('slug'); a.add_argument('--reason', required=True)
    a = commands.add_parser('reopen'); a.add_argument('slug'); a.add_argument('--step', required=True); a.add_argument('--revision', required=True); a.add_argument('--reason', required=True)
    a = commands.add_parser('migrate'); a.add_argument('slug'); a.add_argument('--apply', metavar='PREVIEW_REVISION')
    a = commands.add_parser('artifact'); a.add_argument('slug'); a.add_argument('phase', choices=['research', 'plan', 'changelog']); a.add_argument('--revision', required=True)
    a = commands.add_parser('backup'); a.add_argument('destination')
    return p


def execute(args):
    ctx = context(args.cwd)
    if args.command == 'context':
        return {k: str(v) for k, v in ctx.items()}
    if args.command == 'active' and args.limit < 1:
        raise WorkflowError('--limit must be positive')
    db = None
    try:
        if args.command == 'active':
            if not (ctx['cwd'] / '.devflow/project.json').exists():
                return active(ctx, None, args.limit)
        db = connect(ctx, create=args.command == 'init', fresh=getattr(args, 'fresh_state', False))
        if args.command in ('route', 'status', 'active', 'validate', 'history', 'artifact'):
            db.execute('BEGIN')  # One consistent database snapshot for each read-only command.
        if args.command == 'init':
            return {'project_id': identity(ctx), 'database': str(db_path(ctx)[0])}
        if args.command == 'active':
            return active(ctx, db, args.limit)
        if args.command in ('route', 'status'):
            return route(ctx, db, args.slug)
        if args.command == 'validate':
            slug = resolve_slug(ctx['vault'], args.slug)
            plan = artifact(ctx['vault'], 'plans', slug)
            if not plan:
                raise WorkflowError('No plan found')
            return {'slug': slug, 'revision': plan['revision'], 'steps': plan_steps(plan)}
        if args.command == 'approve':
            return approve(ctx, db, args.slug, args.phase, args.revision)
        if args.command == 'start':
            return start(ctx, db, args.slug, args.step, args.revision)
        if args.command == 'finish':
            return finish(ctx, db, args.run_id, args.status, args.changelog, args.reason)
        if args.command == 'interrupt':
            return interrupt(db, args.run_id, args.reason)
        if args.command == 'resume':
            return resume(ctx, db, args.slug, args.reason)
        if args.command == 'reopen':
            return reopen(ctx, db, args.slug, args.step, args.revision, args.reason)
        if args.command == 'migrate':
            return migrate(ctx, db, args.slug, args.apply)
        if args.command == 'history':
            slug = resolve_slug(ctx['vault'], args.slug)
            return [dict(r, data=json.loads(r['data'])) for r in db.execute('SELECT * FROM events WHERE slug=? ORDER BY id', (slug,))]
        if args.command == 'artifact':
            slug = resolve_slug(ctx['vault'], args.slug)
            row = db.execute('SELECT * FROM artifacts WHERE slug=? AND phase=? AND revision=?',
                             (slug, args.phase, args.revision)).fetchone()
            if not row:
                raise WorkflowError('No saved artifact at this revision')
            return dict(row)
        if args.command == 'backup':
            dest = Path(args.destination).resolve()
            if dest.exists():
                raise WorkflowError('Backup destination already exists')
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents accidentally overwriting a database or an older backup.
            with dest.open('xb'):
                pass
            out = sqlite3.connect(dest)
            try:
                db.backup(out)
            finally:
                out.close()
            return {'backup': str(dest), 'project_id': identity(ctx),
                    'also_copy': str(ctx['cwd'] / '.devflow/project.json')}
    finally:
        if db is not None:
            db.close()


def main():
    try:
        result = execute(parser().parse_args())
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (WorkflowError, OSError, ValueError, KeyError, sqlite3.Error, yaml.YAMLError) as exc:
        print(json.dumps({'state': 'invalid', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0
