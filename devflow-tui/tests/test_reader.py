"""Tests for DevFlow TUI data reader."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from devflow_tui.data.models import (
    DISPLAY_PHASES,
    PHASE_LABELS,
    PHASE_ORDER,
    QueueData,
    Session,
)
from devflow_tui.data.reader import DevFlowData

SAMPLE_SESSIONS = {
    "version": "1.0",
    "sessions": {
        "DF-3-work": {
            "skill": "develop",
            "feature": "DF-3: Background queue",
            "project": "devflow",
            "started_at": "2026-03-03T13:12:21Z",
            "updated_at": "2026-03-03T13:28:35Z",
            "status": "completed",
            "current_phase": "phase_9_summary",
            "completed_phases": [
                "phase_0_config",
                "phase_1_branch",
                "phase_2_plan",
                "phase_2.5_contract",
                "phase_3_implement",
                "phase_7_review",
            ],
            "phase_data": {
                "phase_2_plan": {
                    "plan_summary": "4 tasks"
                }
            },
            "loops": {
                "arch_validation": {"attempt": 0, "max_attempts": 3},
                "review_fix": {"attempt": 0, "max_attempts": 2},
                "test_fix": {"attempt": 0, "max_attempts": 2},
            },
            "branches": {"work": "DF-3-work", "final": "DF-3"},
            "repos": ["main"],
            "phase_history": [
                {
                    "phase": "phase_1_branch",
                    "completed_at": "2026-03-03T13:12:23Z",
                    "duration_seconds": 2,
                    "result": "success",
                    "reason": "",
                },
                {
                    "phase": "phase_2_plan",
                    "completed_at": "2026-03-03T13:18:47Z",
                    "duration_seconds": 384,
                    "result": "success",
                    "reason": "",
                },
                {
                    "phase": "phase_2.5_contract",
                    "completed_at": "2026-03-03T13:19:09Z",
                    "duration_seconds": 21,
                    "result": "skipped",
                    "reason": "meta-project, no contract needed",
                },
            ],
        },
        "DF-4-work": {
            "skill": "develop",
            "feature": "DF-4: TUI monitor",
            "project": "devflow",
            "started_at": "2026-03-03T19:07:40Z",
            "updated_at": "2026-03-03T19:10:00Z",
            "status": "running",
            "current_phase": "phase_3_implement",
            "completed_phases": [
                "phase_0_config",
                "phase_1_branch",
                "phase_2_plan",
                "phase_2.5_contract",
            ],
            "phase_data": {},
            "loops": {
                "arch_validation": {"attempt": 0, "max_attempts": 3},
                "review_fix": {"attempt": 0, "max_attempts": 2},
                "test_fix": {"attempt": 0, "max_attempts": 2},
            },
            "branches": {"work": "DF-4-work", "final": "DF-4"},
            "repos": ["main"],
            "phase_history": [],
        },
    },
}

SAMPLE_QUEUE = {
    "version": "1.0",
    "queue": [
        {
            "id": 1,
            "project": "devflow",
            "skill": "develop",
            "args": "Add dark mode",
            "status": "completed",
            "added_at": "2026-03-03T10:00:00Z",
            "started_at": "2026-03-03T10:01:00Z",
            "completed_at": "2026-03-03T10:30:00Z",
            "result": "completed",
            "branch": "feature/dark-mode",
            "error": None,
        },
        {
            "id": 2,
            "project": "devflow",
            "skill": "fix",
            "args": "Login timeout bug",
            "status": "running",
            "added_at": "2026-03-03T10:00:00Z",
            "started_at": "2026-03-03T10:31:00Z",
            "completed_at": None,
            "result": None,
            "branch": None,
            "error": None,
        },
        {
            "id": 3,
            "project": "devflow",
            "skill": "refactor",
            "args": "Extract validation",
            "status": "pending",
            "added_at": "2026-03-03T10:00:00Z",
            "started_at": None,
            "completed_at": None,
            "result": None,
            "branch": None,
            "error": None,
        },
    ],
    "last_run": {
        "started_at": "2026-03-03T10:00:00Z",
        "completed_at": "2026-03-03T10:30:00Z",
        "total": 3,
        "completed": 1,
        "failed": 0,
        "skipped": 0,
    },
    "background_run": None,
    "next_id": 4,
}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Create a temp directory with sample data files."""
    claude_data = tmp_path / ".claude" / "data"
    claude_data.mkdir(parents=True)

    with open(claude_data / "sessions.json", "w") as f:
        json.dump(SAMPLE_SESSIONS, f)

    with open(claude_data / "queue.json", "w") as f:
        json.dump(SAMPLE_QUEUE, f)

    return tmp_path


@pytest.fixture
def reader(data_dir: Path) -> DevFlowData:
    return DevFlowData(str(data_dir), "devflow")


class TestSessionParsing:
    def test_parse_all_sessions(self, reader: DevFlowData) -> None:
        sessions = reader.get_all_sessions()
        assert len(sessions) == 2

    def test_active_session(self, reader: DevFlowData) -> None:
        active = reader.get_active_session()
        assert active is not None
        assert active.key == "DF-4-work"
        assert active.status == "running"
        assert active.skill == "develop"

    def test_no_active_when_none_running(self, data_dir: Path) -> None:
        # Modify to have no running sessions
        sessions_path = data_dir / ".claude" / "data" / "sessions.json"
        with open(sessions_path) as f:
            data = json.load(f)
        data["sessions"]["DF-4-work"]["status"] = "completed"
        with open(sessions_path, "w") as f:
            json.dump(data, f)

        reader = DevFlowData(str(data_dir), "devflow")
        assert reader.get_active_session() is None

    def test_recent_sessions_sorted(self, reader: DevFlowData) -> None:
        recent = reader.get_recent_sessions(limit=5)
        assert len(recent) == 2
        # DF-4-work has later updated_at, should be first
        assert recent[0].key == "DF-4-work"
        assert recent[1].key == "DF-3-work"

    def test_session_duration(self, reader: DevFlowData) -> None:
        session = reader.get_session("DF-3-work")
        assert session is not None
        assert session.duration_display == "16m"

    def test_session_phase_status(self, reader: DevFlowData) -> None:
        session = reader.get_session("DF-4-work")
        assert session is not None
        assert session.phase_status("phase_0_config") == "completed"
        assert session.phase_status("phase_3_implement") == "current"
        assert session.phase_status("phase_7_review") == "pending"

    def test_session_skipped_phase(self, reader: DevFlowData) -> None:
        session = reader.get_session("DF-3-work")
        assert session is not None
        # phase_2.5_contract was skipped per phase_history
        assert session.phase_status("phase_2.5_contract") == "skipped"

    def test_phase_history(self, reader: DevFlowData) -> None:
        session = reader.get_session("DF-3-work")
        assert session is not None
        assert len(session.phase_history) == 3
        assert session.phase_history[0].phase == "phase_1_branch"
        assert session.phase_history[0].duration_seconds == 2

    def test_loops(self, reader: DevFlowData) -> None:
        session = reader.get_session("DF-4-work")
        assert session is not None
        assert len(session.loops) == 3
        assert all(lp.attempt == 0 for lp in session.loops)


class TestQueueParsing:
    def test_parse_queue(self, reader: DevFlowData) -> None:
        queue = reader.get_queue()
        assert len(queue.items) == 3

    def test_queue_pending(self, reader: DevFlowData) -> None:
        queue = reader.get_queue()
        assert len(queue.pending_items) == 1
        assert queue.pending_items[0].skill == "refactor"

    def test_queue_running(self, reader: DevFlowData) -> None:
        queue = reader.get_queue()
        running = queue.running_item
        assert running is not None
        assert running.id == 2
        assert running.skill == "fix"

    def test_queue_counts(self, reader: DevFlowData) -> None:
        queue = reader.get_queue()
        assert queue.completed_count == 1
        assert queue.failed_count == 0

    def test_last_run(self, reader: DevFlowData) -> None:
        queue = reader.get_queue()
        assert queue.last_run is not None
        assert queue.last_run.total == 3
        assert queue.last_run.completed == 1

    def test_queue_item_description(self, reader: DevFlowData) -> None:
        queue = reader.get_queue()
        assert queue.items[0].description == "Add dark mode"


class TestReaderReload:
    def test_reload_clears_cache(self, reader: DevFlowData, data_dir: Path) -> None:
        # Initial read
        active = reader.get_active_session()
        assert active is not None

        # Modify file
        sessions_path = data_dir / ".claude" / "data" / "sessions.json"
        with open(sessions_path) as f:
            data = json.load(f)
        data["sessions"]["DF-4-work"]["status"] = "completed"
        with open(sessions_path, "w") as f:
            json.dump(data, f)

        # Without reload, cache returns old data
        active_cached = reader.get_active_session()
        assert active_cached is not None  # still cached

        # After reload, returns new data
        reader.reload()
        active_new = reader.get_active_session()
        assert active_new is None

    def test_missing_files(self, tmp_path: Path) -> None:
        reader = DevFlowData(str(tmp_path), "devflow")
        assert reader.get_all_sessions() == []
        assert reader.get_active_session() is None
        queue = reader.get_queue()
        assert len(queue.items) == 0


class TestModels:
    def test_phase_order_has_labels(self) -> None:
        for phase in PHASE_ORDER:
            assert phase in PHASE_LABELS

    def test_display_phases_subset(self) -> None:
        for phase in DISPLAY_PHASES:
            assert phase in PHASE_ORDER

    def test_status_icons(self) -> None:
        s = Session.from_dict("test", {
            "skill": "develop",
            "feature": "test",
            "status": "running",
        })
        assert s.status_icon != ""

    def test_session_from_minimal_dict(self) -> None:
        s = Session.from_dict("test", {"skill": "fix", "feature": "bug"})
        assert s.key == "test"
        assert s.skill == "fix"
        assert s.started_at is None
        assert s.duration_display == "-"
