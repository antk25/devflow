import os
import subprocess
from pathlib import Path

import pytest

LCURL = Path(__file__).resolve().parent.parent / "bin" / "lcurl"
URL = "http://localhost:8080/"


@pytest.fixture
def fake_curl(tmp_path):
    marker = tmp_path / "called"
    curl = tmp_path / "curl"
    curl.write_text(f'#!/usr/bin/env bash\ntouch "{marker}"\nprintf "%s\\n" "$@"\n')
    curl.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}

    def run(*args):
        return subprocess.run([str(LCURL), *args], env=env, capture_output=True, text=True)

    run.marker = marker
    return run


LONG_FLAGS = ["--proxy", "--proxy1.0", "--preproxy", "--socks4", "--socks4a", "--socks5",
              "--socks5-hostname", "--resolve", "--connect-to", "--config", "--doh-url"]

CASES = (
    [([flag, "evil.example:1"], flag) for flag in LONG_FLAGS]
    + [([f"{flag}=evil.example:1"], flag) for flag in LONG_FLAGS]
    + [
        (["-x", "evil.example:1"], "-x"),
        (["-xevil.example:1"], "-x"),
        (["-K", "cfg"], "-K"),
        (["-Kcfg"], "-K"),
        (["-sx", "evil.example:1"], "-x"),
        (["-sK", "cfg"], "-K"),
    ]
)


@pytest.mark.parametrize("args,flag", CASES)
def test_forbidden_flag_refused(fake_curl, args, flag):
    result = fake_curl(*args, URL)
    assert result.returncode != 0
    assert f"'{flag}'" in result.stderr
    assert not fake_curl.marker.exists()


def test_local_request_passes_args_through(fake_curl):
    args = ["-s", "-o", "/dev/null", "-w", "%{http_code}", URL]
    result = fake_curl(*args)
    assert result.returncode == 0
    assert result.stdout.splitlines() == args


def test_external_host_refused(fake_curl):
    result = fake_curl("https://example.com")
    assert result.returncode == 3
    assert not fake_curl.marker.exists()
