"""Data models for DevFlow session and queue data."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

PHASE_ORDER: list[str] = [
    "phase_0_config",
    "phase_1_branch",
    "phase_1.5_trace",
    "phase_2_plan",
    "phase_2.5_contract",
    "phase_2.7_test_first",
    "phase_3_implement",
    "phase_3.5_test_isolation",
    "phase_4_validate",
    "phase_5_e2e",
    "phase_6_commit",
    "phase_6.5_test_reaction",
    "phase_7_review",
    "phase_8_fix",
    "phase_9_summary",
]

PHASE_LABELS: dict[str, str] = {
    "phase_0_config": "Config",
    "phase_1_branch": "Branch",
    "phase_1.5_trace": "Trace",
    "phase_2_plan": "Plan",
    "phase_2.5_contract": "Contract",
    "phase_2.7_test_first": "Test-First",
    "phase_3_implement": "Implement",
    "phase_3.5_test_isolation": "Test-Iso",
    "phase_4_validate": "Validate",
    "phase_5_e2e": "E2E",
    "phase_6_commit": "Commit",
    "phase_6.5_test_reaction": "Test-React",
    "phase_7_review": "Review",
    "phase_8_fix": "Fix",
    "phase_9_summary": "Summary",
}

# Phases shown in the compact progress bar (skip internal/minor phases)
DISPLAY_PHASES: list[str] = [
    "phase_0_config",
    "phase_1_branch",
    "phase_1.5_trace",
    "phase_2_plan",
    "phase_2.5_contract",
    "phase_3_implement",
    "phase_4_validate",
    "phase_5_e2e",
    "phase_7_review",
    "phase_9_summary",
]

STATUS_ICONS: dict[str, str] = {
    "completed": "\u2705",
    "running": "\u23f3",
    "failed": "\u274c",
    "interrupted": "\u26a0\ufe0f",
    "pending": "\u2b1c",
    "review_ready": "\u2705",
    "skipped": "\u23e9",
}


_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


@dataclass
class PhaseEntry:
    """A single phase execution record from phase_history."""

    phase: str
    completed_at: datetime | None
    duration_seconds: int
    result: str  # success, skipped, failed
    reason: str = ""

    @property
    def label(self) -> str:
        return PHASE_LABELS.get(self.phase, self.phase)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PhaseEntry:
        return cls(
            phase=d.get("phase", ""),
            completed_at=_parse_ts(d.get("completed_at")),
            duration_seconds=int(d.get("duration_seconds", 0)),
            result=d.get("result", ""),
            reason=d.get("reason", ""),
        )


@dataclass
class LoopInfo:
    """Loop detection info (arch_validation, review_fix, test_fix)."""

    name: str
    attempt: int
    max_attempts: int

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> LoopInfo:
        return cls(
            name=name,
            attempt=int(d.get("attempt", 0)),
            max_attempts=int(d.get("max_attempts", 3)),
        )


@dataclass
class Session:
    """A DevFlow session from sessions.json."""

    key: str
    skill: str
    feature: str
    project: str
    started_at: datetime | None
    updated_at: datetime | None
    status: str
    current_phase: str
    completed_phases: list[str] = field(default_factory=list)
    phase_data: dict[str, Any] = field(default_factory=dict)
    loops: list[LoopInfo] = field(default_factory=list)
    branches: dict[str, str] = field(default_factory=dict)
    repos: list[str] = field(default_factory=list)
    phase_history: list[PhaseEntry] = field(default_factory=list)

    @property
    def work_branch(self) -> str:
        return self.branches.get("work", self.key)

    @property
    def final_branch(self) -> str:
        return self.branches.get("final", "")

    @property
    def status_icon(self) -> str:
        return STATUS_ICONS.get(self.status, "\u2753")

    @property
    def duration_seconds(self) -> int | None:
        if not self.started_at:
            return None
        end = self.updated_at or datetime.now(timezone.utc)
        return int((end - self.started_at).total_seconds())

    @property
    def duration_display(self) -> str:
        secs = self.duration_seconds
        if secs is None:
            return "-"
        if secs < 60:
            return "< 1m"
        minutes = secs // 60
        if minutes < 60:
            return f"{minutes}m"
        hours = minutes // 60
        mins = minutes % 60
        if mins == 0:
            return f"{hours}h"
        return f"{hours}h {mins}m"

    @property
    def current_phase_label(self) -> str:
        return PHASE_LABELS.get(self.current_phase, self.current_phase)

    def phase_status(self, phase: str) -> str:
        """Return 'completed', 'current', 'skipped', or 'pending' for a phase."""
        if phase in self.completed_phases:
            # Check phase_history for skip info
            for entry in self.phase_history:
                if entry.phase == phase and entry.result == "skipped":
                    return "skipped"
            return "completed"
        if phase == self.current_phase:
            return "current"
        return "pending"

    @classmethod
    def from_dict(cls, key: str, d: dict[str, Any]) -> Session:
        loops = []
        for name, loop_data in d.get("loops", {}).items():
            if isinstance(loop_data, dict):
                loops.append(LoopInfo.from_dict(name, loop_data))

        history = []
        for entry in d.get("phase_history", []):
            if isinstance(entry, dict):
                history.append(PhaseEntry.from_dict(entry))

        return cls(
            key=key,
            skill=d.get("skill", ""),
            feature=d.get("feature", ""),
            project=d.get("project", ""),
            started_at=_parse_ts(d.get("started_at")),
            updated_at=_parse_ts(d.get("updated_at")),
            status=d.get("status", ""),
            current_phase=d.get("current_phase", ""),
            completed_phases=d.get("completed_phases", []),
            phase_data=d.get("phase_data", {}),
            loops=loops,
            branches=d.get("branches", {}),
            repos=d.get("repos", []),
            phase_history=history,
        )


@dataclass
class QueueItem:
    """A single item in the task queue."""

    id: int
    project: str
    skill: str
    args: str
    status: str
    added_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    result: str | None
    branch: str | None
    error: str | None

    @property
    def status_icon(self) -> str:
        return STATUS_ICONS.get(self.status, "\u2753")

    @property
    def description(self) -> str:
        return self.args.split("\n")[0][:80].strip() if self.args else ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> QueueItem:
        return cls(
            id=int(d.get("id", 0)),
            project=d.get("project", ""),
            skill=d.get("skill", ""),
            args=d.get("args", ""),
            status=d.get("status", "pending"),
            added_at=_parse_ts(d.get("added_at")),
            started_at=_parse_ts(d.get("started_at")),
            completed_at=_parse_ts(d.get("completed_at")),
            result=d.get("result"),
            branch=d.get("branch"),
            error=d.get("error"),
        )


@dataclass
class LastRun:
    """Last queue run summary."""

    started_at: datetime | None
    completed_at: datetime | None
    total: int
    completed: int
    failed: int
    skipped: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LastRun:
        return cls(
            started_at=_parse_ts(d.get("started_at")),
            completed_at=_parse_ts(d.get("completed_at")),
            total=int(d.get("total", 0)),
            completed=int(d.get("completed", 0)),
            failed=int(d.get("failed", 0)),
            skipped=int(d.get("skipped", 0)),
        )


@dataclass
class BackgroundRun:
    """Background queue run state."""

    tmux_session: str
    started_at: datetime | None
    status: str  # running, completed, stopped
    stopped_at: datetime | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BackgroundRun:
        return cls(
            tmux_session=d.get("tmux_session", ""),
            started_at=_parse_ts(d.get("started_at")),
            status=d.get("status", ""),
            stopped_at=_parse_ts(d.get("stopped_at")),
        )


@dataclass
class QueueData:
    """Full queue state."""

    items: list[QueueItem] = field(default_factory=list)
    last_run: LastRun | None = None
    background_run: BackgroundRun | None = None

    @property
    def pending_items(self) -> list[QueueItem]:
        return [i for i in self.items if i.status == "pending"]

    @property
    def running_item(self) -> QueueItem | None:
        for i in self.items:
            if i.status == "running":
                return i
        return None

    @property
    def completed_count(self) -> int:
        return sum(1 for i in self.items if i.status == "completed")

    @property
    def failed_count(self) -> int:
        return sum(1 for i in self.items if i.status == "failed")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> QueueData:
        items = [QueueItem.from_dict(i) for i in d.get("queue", [])]

        last_run = None
        if d.get("last_run"):
            last_run = LastRun.from_dict(d["last_run"])

        bg = None
        if d.get("background_run"):
            bg = BackgroundRun.from_dict(d["background_run"])

        return cls(items=items, last_run=last_run, background_run=bg)
