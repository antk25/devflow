"""Narrow, state-independent transport for the installed Codex review CLI."""
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

from .documents import WorkflowError
from .guard import git_output
from .pi import _cleanup_process_group


def run_review(ctx, *, repo=None, base=None, commit=None, uncommitted=False, message_file=None,
               title=None, timeout=600):
    project = Path(ctx['cwd']).resolve()
    cwd = Path(repo if repo is not None else project).resolve()
    roots = [Path('/tmp').resolve(), Path('/var/tmp').resolve()]
    root = next((p for p in roots if p != cwd and not p.is_relative_to(cwd)), None)
    if root is None:
        raise ValueError('No temporary directory outside repository')
    directory = Path(tempfile.mkdtemp(prefix='devflow-codex-review-', dir=root)).resolve()
    result = dict(exit_code=1, timed_out=False, error=None, cwd=str(cwd), argv=[],
                  **{name: str(directory / filename) for name, filename in (
                      ('request', 'request.md'), ('stdout', 'stdout.log'),
                      ('stderr', 'stderr.log'), ('manifest', 'manifest.json'))})
    child = None
    try:
        Path(result['request']).write_text('', encoding='utf-8')
        with Path(result['stdout']).open('wb') as out, Path(result['stderr']).open('wb') as err:
            if cwd != project and not cwd.is_relative_to(project):
                raise ValueError(f'Repository {cwd} is outside project {project}')
            if not (cwd / '.git').exists():
                raise ValueError(f'{cwd} is not a git repository; in a metarepo pass --repo <subdirectory>')
            if sum((base is not None, commit is not None, bool(uncommitted), message_file is not None)) != 1:
                raise ValueError('Exactly one review mode is required')
            if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
                raise ValueError('timeout must be finite and positive')
            for name, value in (('base', base), ('commit', commit), ('title', title)):
                if value is not None and (not isinstance(value, str) or not value.strip() or '\0' in value):
                    raise ValueError(f'Invalid {name}')
            argv = ['codex', 'review']
            if base is not None:
                argv += ['--base', base]
            elif commit is not None:
                argv += ['--commit', commit]
            elif uncommitted:
                argv += ['--uncommitted']
            if title is not None:
                argv += ['--title', title]
            if message_file is not None:
                prompt = Path(message_file).read_text(encoding='utf-8')
                if not prompt.strip() or '\0' in prompt or prompt == '-':
                    raise ValueError('Invalid review prompt')
                Path(result['request']).write_text(prompt, encoding='utf-8')
                argv += ['--', prompt]
            else:
                Path(result['request']).write_text(json.dumps(
                    dict(base=base, commit=commit, uncommitted=uncommitted, title=title),
                    ensure_ascii=False), encoding='utf-8')
            result['argv'] = argv
            try:
                child = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                                         stdout=out, stderr=err, start_new_session=True, shell=False)
                result['exit_code'] = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                result.update(exit_code=124, timed_out=True, error='timeout')
            finally:
                if child is not None:
                    try:
                        _cleanup_process_group(child)
                    except (OSError, subprocess.TimeoutExpired) as exc:
                        result['error'] = (result['error'] + '; ' if result['error'] else '') + f'cleanup: {exc}'
                        result['exit_code'] = result['exit_code'] or 1
    except (OSError, ValueError, TypeError) as exc:
        result.update(exit_code=1, error=str(exc))
    if result['exit_code'] != 0 and result['error'] is None:
        result['error'] = f"Codex exited with {result['exit_code']}"
    if result['error'] is None and not Path(result['stdout']).stat().st_size:
        result['error'] = 'Empty Codex response; review incomplete'
    Path(result['manifest']).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def _origin_head(path):
    return git_output(path, 'symbolic-ref', '--short', 'refs/remotes/origin/HEAD').removeprefix('origin/') or None


def review_repos(ctx, slug):
    match = re.match(r'([a-z]+-\d+)(?:-|$)', slug.lower())
    if not match:
        raise WorkflowError(f'No task key in slug {slug!r}')
    key = match.group(1).upper()
    root = Path(ctx['cwd']).resolve()
    if (root / '.git').exists():
        agents = root / 'AGENTS.md'
        text = agents.read_text(encoding='utf-8') if agents.is_file() else ''
        found = re.search(r'^\s*-\s*Base branch:\s*`([^`]+)`', text, re.M)
        base = found.group(1) if found else _origin_head(root)
        repo = dict(repo='.', path=str(root), branch=git_output(root, 'branch', '--show-current') or None,
                    base=base, head=git_output(root, 'rev-parse', 'HEAD') or None, error=None)
        if base is None:
            repo['error'] = 'No Base branch in AGENTS.md and no origin/HEAD'
        return {'key': key, 'repos': [repo]}
    repos = []
    for path in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith('.') and (p / '.git').exists()):
        branches = [b for b in git_output(path, 'branch', '--format=%(refname:short)').splitlines()
                    if key.lower() in b.lower()]
        if not branches:
            continue
        current = git_output(path, 'branch', '--show-current')
        repo = dict(repo=path.name, path=str(path), branch=None, base=_origin_head(path),
                    head=git_output(path, 'rev-parse', 'HEAD') or None, error=None)
        if current in branches:
            repo['branch'] = current
        elif len(branches) == 1:
            repo.update(branch=branches[0], error=f'Task branch {branches[0]} is not checked out')
        else:
            repo['error'] = f'Several task branches, none checked out: {", ".join(branches)}'
        if repo['base'] is None and repo['error'] is None:
            repo['error'] = 'No origin/HEAD'
        repos.append(repo)
    return {'key': key, 'repos': repos}
