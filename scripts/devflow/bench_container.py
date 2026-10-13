"""Docker side of the benchmark: the internal network, the task container and command execution in it.

The runners (claude, pi) run on the host for now — `RUNNER_MODE = 'host'` — because the subscription
login cannot be moved into a container without a `CLAUDE_CODE_OAUTH_TOKEN`. The task repository is
checked out of the SWE-bench image into a host work directory, bind-mounted into the task container
at the same path; tests and other task commands run inside through `docker exec`. Switching to the
in-container variant means `RUNNER_MODE = 'container'` plus an image with the runners installed.
"""
import os
import shutil
import subprocess
from pathlib import Path

NETWORK = 'devflow-bench'
RUNNER_MODE = 'host'
CONTAINER_HOME = '/tmp/devflow-home'


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
    """A copy of the task repository from the image in `dest` (replaced when it exists), owned by the caller."""
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
    return dest


def run_command(name, image, workdir, env_names=()):
    """argv of the task container: host uid/gid, the work directory mounted at its own path, secrets passed by
    variable name only, no network except the internal one."""
    workdir = str(workdir)
    cmd = ['docker', 'run', '-d', '--name', name, '--network', NETWORK, '--user', f'{os.getuid()}:{os.getgid()}',
           '-e', f'HOME={CONTAINER_HOME}']
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
