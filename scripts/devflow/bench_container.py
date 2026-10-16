"""Docker side of the benchmark: the internal network, the task container and command execution in it.

The runners (claude, pi) run on the host for now — `RUNNER_MODE = 'host'` — because the subscription
login cannot be moved into a container without a `CLAUDE_CODE_OAUTH_TOKEN`. The task repository is
checked out of the SWE-bench image into a host work directory, bind-mounted into the task container
at the same path; tests and other task commands run inside through `docker exec`. Switching to the
in-container variant means `RUNNER_MODE = 'container'` plus an image with the runners installed.
"""
import os
import shlex
import shutil
import subprocess
from pathlib import Path

NETWORK = 'devflow-bench'
RUNNER_MODE = 'host'
CONTAINER_HOME = '/tmp/devflow-home'
# Images keep tool caches under /root, unreadable by the host uid; each is copied next to the repository
# and pointed at through its variable: (path in the image, copy relative to the work directory, variable).
ROOT_CACHES = (('/root/go/pkg/mod', 'go/pkg/mod', 'GOMODCACHE'),
               ('/root/.cache/node/corepack', 'node/corepack', 'COREPACK_HOME'),
               ('/root/.yarn/berry', 'yarn/berry', 'YARN_GLOBAL_FOLDER'))
GO_MOD_CACHE, GO_MOD_CACHE_COPY = ROOT_CACHES[0][:2]


def docker_execute(cmd, timeout, cwd=None, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                          timeout=timeout)


def ensure_network(execute=docker_execute):
    """The internal network `devflow-bench`; created when missing. Returns the value of `Internal`."""
    proc = execute(['docker', 'network', 'inspect', '--format', '{{.Internal}}', NETWORK], 60)
    if proc.returncode != 0:
        proc = execute(['docker', 'network', 'create', '--internal', NETWORK], 60)
        if proc.returncode != 0:
            raise RuntimeError(f'docker network create {NETWORK} failed: {(proc.stderr or "").strip()}')
        proc = execute(['docker', 'network', 'inspect', '--format', '{{.Internal}}', NETWORK], 60)
    return (proc.stdout or '').strip() == 'true'


def checkout(image, dest, execute=docker_execute, source='/testbed'):
    """A copy of the task repository from the image in `dest` (replaced when it exists), owned by the caller;
    the root caches of the image (`ROOT_CACHES`), when present, go beside `dest`."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    proc = execute(['docker', 'create', image], 600)
    if proc.returncode != 0:
        raise RuntimeError(f'docker create {image} failed: {(proc.stderr or "").strip()}')
    cid = proc.stdout.strip()
    try:
        proc = execute(['docker', 'cp', f'{cid}:{source}/.', str(dest)], 1800)
        if proc.returncode != 0:
            raise RuntimeError(f'docker cp {source} failed: {(proc.stderr or "").strip()}')
    finally:
        execute(['docker', 'rm', cid], 60)
    copy_root_caches(image, dest.parent, execute)
    return dest


def cache_env(workdir):
    return [f'{var}={workdir}/{copy}' for _, copy, var in ROOT_CACHES]


def copy_root_caches(image, workdir, execute=docker_execute):
    """The `ROOT_CACHES` of the image into `<workdir>`, writable and owned by the host user.
    `docker cp` cannot do it: the cache directories are read-only and the copy stops at the second file."""
    workdir = Path(workdir)
    tops = sorted({Path(copy).parts[0] for _, copy, _ in ROOT_CACHES})
    for top in tops:
        if (workdir / top).exists():
            shutil.rmtree(workdir / top)
    steps = []
    for source, copy, _ in ROOT_CACHES:
        target = workdir / copy
        steps.append(f'if [ -d {source} ]; then mkdir -p {shlex.quote(str(target.parent))} && '
                     f'cp -a {source} {shlex.quote(str(target))} || exit 1; fi')
    owned = ' '.join(shlex.quote(str(workdir / top)) for top in tops)
    script = '\n'.join(steps + [f'for d in {owned}; do [ -d "$d" ] && chmod -R u+w "$d" && '
                                 f'chown -R {os.getuid()}:{os.getgid()} "$d"; done; exit 0'])
    proc = execute(['docker', 'run', '--rm', '--network', 'none', '-v', f'{workdir}:{workdir}', '--entrypoint', 'sh',
                    image, '-c', script], 1800)
    if proc.returncode != 0:
        raise RuntimeError(f'root cache copy from {image} failed: {(proc.stderr or "").strip()}')
    return [workdir / copy for _, copy, _ in ROOT_CACHES if (workdir / copy).exists()]


def run_command(name, image, workdir, env_names=()):
    """argv of the task container: host uid/gid, the work directory mounted at its own path, secrets passed by
    variable name only, no network except the internal one."""
    workdir = str(workdir)
    cmd = ['docker', 'run', '-d', '--name', name, '--network', NETWORK, '--user', f'{os.getuid()}:{os.getgid()}',
           '-e', f'HOME={CONTAINER_HOME}']
    for pair in cache_env(workdir):
        cmd += ['-e', pair]
    for env_name in env_names:
        cmd += ['-e', env_name]
    cmd += ['-v', f'{workdir}:{workdir}', '-w', workdir, '--entrypoint', 'sleep', image, 'infinity']
    return cmd


def start(name, image, workdir, env_names=(), execute=docker_execute):
    stop(name, execute)
    proc = execute(run_command(name, image, workdir, env_names), 600)
    if proc.returncode != 0:
        raise RuntimeError(f'docker run {image} failed: {(proc.stderr or "").strip()}')


def stop(name, execute=docker_execute):
    execute(['docker', 'rm', '-f', name], 120)


def executor(name, cwd, env=None, execute=None):
    """`(cmd, timeout) -> CompletedProcess` through `docker exec -w <cwd>`; on timeout the container is stopped."""
    execute = execute or docker_execute
    prefix = ['docker', 'exec', '-w', str(cwd)]
    for key, value in (env or {}).items():
        prefix += ['-e', f'{key}={value}']
    prefix.append(name)

    def run(cmd, timeout):
        try:
            return execute(prefix + list(cmd), timeout)
        except subprocess.TimeoutExpired:
            stop(name, execute)
            raise
    return run


def host_executor(cwd, env=None):
    """`(cmd, timeout) -> CompletedProcess` on the host with closed stdin; `env` is added to the inherited one."""
    merged = dict(os.environ, **(env or {}))

    def run(cmd, timeout):
        return docker_execute(cmd, timeout, cwd=str(cwd), env=merged)
    return run


def runner_executor(name, cwd, env=None):
    """Where runner commands go: the host today, the task container once RUNNER_MODE is 'container'."""
    if RUNNER_MODE == 'container':
        return executor(name, cwd, env)
    return host_executor(cwd, env)


def shell(execute, script, timeout):
    return execute(['sh', '-c', script], timeout)


OFFLINE_SCRIPT = ('if command -v curl >/dev/null 2>&1; then exec curl -sS -m 10 -o /dev/null https://github.com; fi; '
                  'exec wget -q -T 10 -O /dev/null https://github.com')
