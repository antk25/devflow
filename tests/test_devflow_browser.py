import os
import re
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parent.parent / "bin" / "devflow-browser"
PACKAGE = "chrome-devtools-mcp@1.10.1"
UUID_RE = re.compile(r"^[0-9a-f-]{36}$")


@pytest.fixture
def browser(tmp_path):
    argv_log = tmp_path / "argv"
    npx = tmp_path / "npx"
    npx.write_text(
        '#!/usr/bin/env bash\n'
        f'printf "%s\\n" "$@" >> "{argv_log}"\n'
        'printf "%s" "${FAKE_NPX_STDOUT:-}"\n'
        'printf "%s" "${FAKE_NPX_STDERR:-}" >&2\n'
        'exit "${FAKE_NPX_RC:-0}"\n'
    )
    npx.chmod(0o755)
    env_file = tmp_path / "browser.env"
    env_file.write_text("SHOP_PASSWORD=hunter2\n# comment\n\nEMPTY=\nADMIN_TOKEN=tok-123\n")
    smoke_dir = tmp_path / "smoke"
    base_env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "DEVFLOW_SMOKE_DIR": str(smoke_dir),
        "DEVFLOW_BROWSER_ENV": str(env_file),
    }

    def run(*args, **fake):
        env = {**base_env, **{f"FAKE_NPX_{k.upper()}": str(v) for k, v in fake.items()}}
        return subprocess.run([str(WRAPPER), *args], env=env, capture_output=True, text=True)

    def calls():
        if not argv_log.exists():
            return []
        return [c.splitlines() for c in argv_log.read_text().split(f"-y\n-p\n{PACKAGE}\nchrome-devtools\n") if c]

    def start():
        result = run("start")
        assert result.returncode == 0, result.stderr
        argv_log.unlink()
        return result.stdout.strip()

    run.calls = calls
    run.start = start
    run.argv_log = argv_log
    run.env_file = env_file
    run.smoke_dir = smoke_dir
    return run


def test_start_prints_uuid_and_marks_session(browser):
    result = browser("start")
    assert result.returncode == 0, result.stderr
    sid = result.stdout.strip()
    assert UUID_RE.match(sid)
    assert (browser.smoke_dir / ".sessions" / sid).is_file()
    assert browser.calls() == [["start", "--isolated", "--headless", "--redactNetworkHeaders", "--sessionId", sid]]


def test_start_insecure_accepts_insecure_certs(browser):
    result = browser("start", "--insecure")
    assert result.returncode == 0, result.stderr
    sid = result.stdout.strip()
    assert browser.calls() == [
        ["start", "--isolated", "--headless", "--redactNetworkHeaders", "--acceptInsecureCerts", "--sessionId", sid]
    ]


def test_start_failure_leaves_no_session(browser):
    result = browser("start", rc=1, stderr="Could not launch Chrome")
    assert result.returncode == 1
    assert "Could not launch Chrome" in result.stderr
    assert not (browser.smoke_dir / ".sessions").exists() or not list((browser.smoke_dir / ".sessions").iterdir())


def test_pinned_version_in_argv(browser):
    browser("start")
    assert browser.argv_log.read_text().startswith(f"-y\n-p\n{PACKAGE}\nchrome-devtools\n")


def test_tool_call_appends_session_id(browser):
    sid = browser.start()
    result = browser(sid, "new_page", "https://example.com", stdout="page 1 opened")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "page 1 opened\n"
    assert browser.calls() == [["new_page", "https://example.com", "--sessionId", sid]]


def test_tool_call_without_start_refused(browser):
    result = browser("9c36c451-b39e-48e2-ad51-fd0c8b62855d", "new_page", "https://example.com")
    assert result.returncode == 3
    assert "devflow-browser start" in result.stderr
    assert browser.calls() == []


def test_garbage_session_id_refused(browser):
    result = browser("new_page", "https://example.com")
    assert result.returncode == 2
    assert "devflow-browser start" in result.stderr
    assert browser.calls() == []


@pytest.mark.parametrize("args", [
    ["start"],
    ["--sessionId", "abc"],
    ["--sessionId=abc"],
    ["--userDataDir", "/tmp/p"],
    ["--userDataDir=/tmp/p"],
    ["--isolated"],
    ["--browserUrl", "http://localhost:9222"],
    ["-u", "http://localhost:9222"],
    ["--wsEndpoint", "ws://x"],
    ["--autoConnect"],
])
def test_forbidden_flag_refused(browser, args):
    sid = browser.start()
    result = browser(sid, "list_pages", *args)
    assert result.returncode == 2
    assert f"'{args[0]}'" in result.stderr
    assert browser.calls() == []


def test_env_reference_substituted_and_masked(browser):
    sid = browser.start()
    result = browser(sid, "type_text", "1", "@env:SHOP_PASSWORD", stdout="typed hunter2 into field", stderr="debug hunter2")
    assert result.returncode == 0
    assert browser.calls() == [["type_text", "1", "hunter2", "--sessionId", sid]]
    assert "hunter2" not in result.stdout + result.stderr
    assert result.stdout == "typed *** into field\n"
    assert result.stderr == "debug ***\n"


def test_env_reference_inside_argument(browser):
    sid = browser.start()
    browser(sid, "evaluate_script", "localStorage.setItem('t', '@env:ADMIN_TOKEN'); '@env:SHOP_PASSWORD'")
    assert browser.calls() == [
        ["evaluate_script", "localStorage.setItem('t', 'tok-123'); 'hunter2'", "--sessionId", sid]
    ]


def test_unknown_env_refused_without_value(browser):
    sid = browser.start()
    result = browser(sid, "type_text", "1", "@env:MISSING")
    assert result.returncode == 4
    assert "MISSING" in result.stderr
    assert "hunter2" not in result.stderr and "tok-123" not in result.stderr
    assert browser.calls() == []


def test_missing_env_file_refused_only_when_referenced(browser):
    browser.env_file.unlink()
    sid = browser.start()
    ok = browser(sid, "list_pages", stdout="pages")
    assert ok.returncode == 0 and ok.stdout == "pages\n"
    result = browser(sid, "type_text", "1", "@env:SHOP_PASSWORD")
    assert result.returncode == 4
    assert "SHOP_PASSWORD" in result.stderr


def test_cli_exit_code_passed_through(browser):
    sid = browser.start()
    result = browser(sid, "click", "1", "9_9", rc=7, stderr="Error: element not found")
    assert result.returncode == 7
    assert result.stderr == "Error: element not found\n"


def test_stop_removes_marker_and_is_idempotent(browser):
    sid = browser.start()
    result = browser(sid, "stop")
    assert result.returncode == 0, result.stderr
    assert browser.calls() == [["stop", "--sessionId", sid]]
    assert not (browser.smoke_dir / ".sessions" / sid).exists()
    browser.argv_log.unlink()
    again = browser(sid, "stop")
    assert again.returncode == 0
    assert browser.calls() == []


def test_no_arguments_refused(browser):
    result = browser()
    assert result.returncode == 2
    assert browser.calls() == []
