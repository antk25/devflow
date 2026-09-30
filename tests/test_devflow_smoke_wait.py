import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parent.parent / "bin" / "devflow-smoke-wait"


@pytest.fixture
def smoke(tmp_path):
    smoke_dir = tmp_path / "smoke"
    env = {**os.environ, "DEVFLOW_SMOKE_DIR": str(smoke_dir)}

    def run(*args):
        return subprocess.run([str(WRAPPER), *args], env=env, capture_output=True, text=True)

    run.dir = smoke_dir
    run.env = env
    return run


def age_activity(smoke, slug, seconds):
    activity = smoke.dir / slug / ".activity"
    past = time.time() - seconds
    os.utime(activity, (past, past))


def mark_session(smoke, slug):
    session_id = str(uuid.uuid4())
    sessions = smoke.dir / ".sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / session_id).write_text(slug)
    return session_id


def fake_browser_call(session_id):
    return subprocess.Popen(
        ["bash", "-c", f'exec -a "devflow-browser {session_id} navigate_page" sleep 30'],
    )


def test_prep_creates_dir_and_fresh_activity(smoke):
    result = smoke("prep", "demo")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    activity = smoke.dir / "demo" / ".activity"
    assert activity.exists()
    assert time.time() - activity.stat().st_mtime < 5


def test_prep_removes_old_verdict_and_is_repeatable(smoke):
    (smoke.dir / "demo").mkdir(parents=True)
    verdict = smoke.dir / "demo" / "verdict.md"
    verdict.write_text("## Вердикт: 1/1 ✅\n")
    screenshot = smoke.dir / "demo" / "1.png"
    screenshot.write_bytes(b"png")
    assert smoke("prep", "demo").returncode == 0
    assert not verdict.exists()
    assert screenshot.exists()
    assert smoke("prep", "demo").returncode == 0


def test_prep_refreshes_stale_activity(smoke):
    smoke("prep", "demo")
    age_activity(smoke, "demo", 500)
    assert smoke("prep", "demo").returncode == 0
    assert time.time() - (smoke.dir / "demo" / ".activity").stat().st_mtime < 5


def test_wait_returns_verdict_path_immediately(smoke):
    smoke("prep", "demo")
    verdict = smoke.dir / "demo" / "verdict.md"
    verdict.write_text("## Вердикт: 2/2 ✅\n")
    started = time.time()
    result = smoke("wait", "demo", "30")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(verdict)
    assert time.time() - started < 3


def test_wait_ignores_empty_verdict_and_hits_limit(smoke):
    smoke("prep", "demo")
    (smoke.dir / "demo" / "verdict.md").write_text("")
    result = smoke("wait", "demo", "2")
    assert result.returncode == 124
    assert result.stdout == ""
    assert len(result.stderr.strip().splitlines()) == 1
    assert "2s" in result.stderr


def test_wait_picks_up_verdict_written_later(smoke):
    smoke("prep", "demo")
    verdict = smoke.dir / "demo" / "verdict.md"
    writer = subprocess.Popen(
        ["bash", "-c", f'sleep 1; printf "## Вердикт: 1/1 ✅\\n" > "{verdict}"'],
    )
    try:
        result = smoke("wait", "demo", "20")
    finally:
        writer.wait()
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(verdict)


def test_wait_reports_dead_browser_after_one_iteration(smoke):
    smoke("prep", "demo")
    age_activity(smoke, "demo", 200)
    started = time.time()
    result = smoke("wait", "demo", "30")
    assert result.returncode == 3
    assert time.time() - started < 3
    assert result.stdout == ""
    assert len(result.stderr.strip().splitlines()) == 1
    assert "120s" in result.stderr


def test_wait_treats_live_browser_call_as_alive(smoke):
    smoke("prep", "demo")
    age_activity(smoke, "demo", 200)
    session_id = mark_session(smoke, "demo")
    proc = fake_browser_call(session_id)
    try:
        result = smoke("wait", "demo", "2")
    finally:
        proc.kill()
        proc.wait()
    assert result.returncode == 124, result.stderr


def test_wait_ignores_live_call_of_other_slug(smoke):
    smoke("prep", "demo")
    age_activity(smoke, "demo", 200)
    session_id = mark_session(smoke, "other")
    proc = fake_browser_call(session_id)
    try:
        result = smoke("wait", "demo", "30")
    finally:
        proc.kill()
        proc.wait()
    assert result.returncode == 3, result.stderr


def test_wait_without_activity_counts_from_start(smoke):
    (smoke.dir / "demo").mkdir(parents=True)
    result = smoke("wait", "demo", "2")
    assert result.returncode == 124, result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ("prep", "Bad_Slug"),
        ("prep",),
        ("wait", "Bad_Slug"),
        ("wait", "demo", "abc"),
        ("wait", "demo", "0"),
        (),
        ("unknown", "demo"),
    ],
)
def test_usage_errors_exit_2(smoke, args):
    result = smoke(*args)
    assert result.returncode == 2, result.stderr
    assert result.stdout == ""
    assert result.stderr.startswith("devflow-smoke-wait:")
