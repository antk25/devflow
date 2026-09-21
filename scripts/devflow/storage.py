"""Project identity and transactional execution state (no document mirrors)."""
import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .documents import WorkflowError

SCHEMA = '''
CREATE TABLE IF NOT EXISTS project (id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts (
 slug TEXT NOT NULL, phase TEXT NOT NULL, revision TEXT NOT NULL, content TEXT NOT NULL,
 PRIMARY KEY (slug, phase, revision));
CREATE TABLE IF NOT EXISTS approvals (
 slug TEXT NOT NULL, phase TEXT NOT NULL, revision TEXT NOT NULL, approved_at TEXT NOT NULL,
 PRIMARY KEY (slug, phase, revision));
CREATE TABLE IF NOT EXISTS steps (
 slug TEXT NOT NULL, id TEXT NOT NULL, revision TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('done','open')), source TEXT NOT NULL,
 PRIMARY KEY (slug, id));
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, slug TEXT NOT NULL, step_id TEXT NOT NULL, step_revision TEXT NOT NULL,
 plan_revision TEXT NOT NULL, research_revision TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('running','done','blocked','partial','resumed')),
 reason TEXT, changelog TEXT, changelog_revision TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS single_running ON runs(status) WHERE status='running';
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, at TEXT NOT NULL, action TEXT NOT NULL, slug TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS migrations (slug TEXT PRIMARY KEY, old_revision TEXT NOT NULL, new_revision TEXT NOT NULL);
'''


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def identity(ctx, create=False):
    path = ctx['cwd'] / '.devflow' / 'project.json'
    if not path.exists():
        if not create:
            raise WorkflowError('Project is not initialized; run devflow init')
        path.parent.mkdir(parents=True, exist_ok=True)
        # A lock also covers first creation, so two launchers cannot choose different IDs.
        import fcntl
        with (path.parent / 'init.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if not path.exists():
                atomic_write(path, json.dumps({'id': str(uuid.uuid4())}, indent=2) + '\n')
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not isinstance(data.get('id'), str):
        raise WorkflowError('Invalid project identity; restore .devflow/project.json from backup')
    return str(uuid.UUID(data['id']))


def db_path(ctx, create=False):
    ident = identity(ctx, create)
    root = Path(os.environ.get('DEVFLOW_STATE_DIR', str(Path.home() / '.local/share/devflow/projects')))
    return root.expanduser().resolve() / ident / 'state.sqlite3', ident


def connect(ctx, create=False, fresh=False):
    if not create:
        return _connect(ctx, False, fresh)
    import fcntl
    local = ctx['cwd'] / '.devflow'
    local.mkdir(parents=True, exist_ok=True)
    with (local / 'state.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _connect(ctx, True, fresh)


def _connect(ctx, create, fresh):
    had_identity = (ctx['cwd'] / '.devflow/project.json').exists()
    path, ident = db_path(ctx, create)
    if create and had_identity and not path.exists() and not fresh:
        raise WorkflowError('Project identity exists but its database is missing; restore the backup or explicitly use init --fresh-state')
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.exists():
        raise WorkflowError('State database is missing; restore it or run devflow init for fresh state')
    existing = path.exists()
    db = sqlite3.connect(path if create else path.as_uri() + '?mode=rw', uri=not create, timeout=10,
                         isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        empty = not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
        if create and (not existing or (fresh and empty)):
            db.executescript('BEGIN IMMEDIATE;\n' + SCHEMA)
            db.execute('INSERT INTO project VALUES (?, 1)', (ident,))
            db.execute('COMMIT')
        row = db.execute('SELECT * FROM project').fetchall()
        if len(row) != 1 or row[0]['id'] != ident or row[0]['schema_version'] != 1:
            raise WorkflowError('Unsupported database version or mismatched project identity')
        return db
    except BaseException:
        db.close()
        raise



@contextmanager
def transaction(db):
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise


def event(db, action, slug, **data):
    db.execute('INSERT INTO events(at,action,slug,data) VALUES (?,?,?,?)',
               (now(), action, slug, json.dumps(data, ensure_ascii=False)))


def remember(db, slug, phase, doc):
    db.execute('INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?)',
               (slug, phase, doc['revision'], doc['raw']))


def approved(db, slug, phase, doc):
    return bool(doc and db.execute('SELECT 1 FROM approvals WHERE slug=? AND phase=? AND revision=?',
                                  (slug, phase, doc['revision'])).fetchone())
