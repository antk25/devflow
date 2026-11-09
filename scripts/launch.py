#!/usr/bin/env python3
"""Validate the selection before updating active, then start the Claude driver or pi."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from devflow import pi
from devflow.cli import active
from devflow.documents import WorkflowError, context, handoff_latest
from devflow.project import registry_path
from devflow.registry import load, select
from devflow.storage import connect


def main():
    root = Path(__file__).resolve().parent.parent
    if sys.argv[1:] == ['--restore-context']:
        print(restore_context(Path.cwd()), end='')
        return 0
    registry = registry_path(root)
    p = argparse.ArgumentParser(description='Choose a project and launch DevFlow')
    p.add_argument('project', nargs='?')
    p.add_argument('--current', '-c', action='store_true')
    p.add_argument('--agent', choices=['claude', 'pi'], default='claude')
    p.add_argument('--model', help='claude: overrides DEVFLOW_MODEL; pi: provider/id[:thinking]')
    p.add_argument('--effort', help='claude: overrides DEVFLOW_EFFORT (default high)')
    args = p.parse_args()
    if args.current and args.project:
        p.error('Use a project name or --current, not both')
    if not registry.exists():
        raise WorkflowError(f'Project registry missing: {registry}. Run ./install.sh first.')
    data = load(registry)
    selected = args.project or (data.get('active') if args.current else None)
    if args.current and not selected:
        raise WorkflowError('No active project; select a project by name')
    if selected is None:
        gum = os.environ.get('GUM') or shutil.which('gum') or shutil.which('gum', path=str(Path.home() / 'bin'))
        if not gum:
            raise WorkflowError('gum is missing; use ./start.sh <project>')
        names = sorted(data['projects'], key=lambda n: (n != data.get('active'), n))
        if not names:
            raise WorkflowError('Project registry is empty')
        choice = subprocess.run([gum, 'choose', '--header', 'Select project:'],
                                input='\n'.join(names) + '\n', text=True, capture_output=True)
        if choice.returncode:
            if choice.stderr:
                print(choice.stderr, file=sys.stderr, end='')
            print('Cancelled.')
            return 0
        selected = choice.stdout.rstrip('\r\n')
    if selected not in data['projects']:
        raise WorkflowError(f'Unknown project {selected!r}. Available: ' + ', '.join(data['projects']))
    path = Path(data['projects'][selected]['path'])
    if not path.is_dir():
        raise WorkflowError(f'Project directory is missing: {path}')
    if args.agent == 'pi':
        executable, argv = pi_command(path, args.model)
    else:
        executable = shutil.which('claude')
        if not executable:
            raise WorkflowError('Claude CLI is missing from PATH')
        if not (path / 'AGENTS.md').exists():
            print(f'{path} has no AGENTS.md. Run /project init {path} inside Claude Code, '
                  f'or: devflow project init {path}')
            if input('Launch without DevFlow project context? [y/N] ').lower() not in ('y', 'yes'):
                return 0
        else:
            ctx = context(path)
            connect(ctx, create=True).close()
        argv = claude_command(executable, args.model, args.effort)
    previous = data.get('active')
    os.chdir(path)
    select(registry, selected)
    print(f'Launching {args.agent} for {selected}: {path}', flush=True)
    try:
        os.execv(executable, argv)
    except OSError:
        # exec failed before the process was replaced; restore this launcher's selection.
        from devflow.storage import atomic_write
        latest = load(registry)
        if latest.get('active') == selected:
            latest['active'] = previous
            atomic_write(registry, json.dumps(latest, ensure_ascii=False, indent=2) + '\n')
        raise


def claude_command(executable, model=None, effort=None):
    model = model or os.environ.get('DEVFLOW_MODEL', 'claude-opus-5-5')
    effort = effort or os.environ.get('DEVFLOW_EFFORT', 'high')
    return [executable, '--model', model, '--effort', effort]


def pi_command(path, model):
    """pi in the project directory with the DevFlow context appended; writes nothing into the project."""
    executable = shutil.which('pi')
    if not executable:
        raise WorkflowError('pi CLI is missing from PATH')
    model = pi.model_arg(os.environ, model)
    pi.ensure_pi_model(model, pi.settings_path(os.environ))
    pi.shared_instructions(Path(os.environ.get('DEVFLOW_INSTRUCTIONS', pi.SHARED_INSTRUCTIONS)))
    argv = [executable, '--extension', str(pi.extension_path(os.environ))] + (['--model', model] if model else [])
    if model:
        os.environ.update(pi.model_env(model))
    if not (path / 'AGENTS.md').exists():
        print(f'WARNING: {path} has no AGENTS.md; launching pi without DevFlow context', file=sys.stderr)
        return executable, argv
    ctx = context(path)
    text = restore_context(path)
    # One file per project, overwritten on every launch: execv leaves nobody to delete a fresh temp file.
    preamble = Path(tempfile.gettempdir()) / f"devflow-pi-{ctx['project']}.md"
    preamble.write_text(text, encoding='utf-8')
    return executable, argv + ['--append-system-prompt', str(preamble)]


def restore_context(path):
    if not (path / 'AGENTS.md').exists():
        return ''
    ctx = context(path)
    db = connect(ctx) if (path / '.devflow/project.json').exists() else None
    try:
        items = active(ctx, db, limit=1000000)
    finally:
        if db:
            db.close()
    try:
        try:
            handoff = handoff_latest(ctx['vault'], pi.task_slug(items))
        except WorkflowError:
            handoff = handoff_latest(ctx['vault'], fresh_minutes=30)
    except WorkflowError as exc:
        return pi.preamble(ctx, items, None) + f'Выберите задачу явно: {exc}\n'
    return pi.preamble(ctx, items, handoff)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (WorkflowError, OSError, ValueError, EOFError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
