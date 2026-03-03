"""Reader for DevFlow session and queue data files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import QueueData, Session, _EPOCH


class DevFlowData:
    """Reads and parses DevFlow data files."""

    def __init__(self, project_path: str, project_name: str = "") -> None:
        self.project_path = Path(project_path)
        self.project_name = project_name
        self.sessions_path = self.project_path / ".claude" / "data" / "sessions.json"
        self.queue_path = self.project_path / ".claude" / "data" / "queue.json"
        self._sessions_cache: dict[str, Session] | None = None
        self._queue_cache: QueueData | None = None

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def reload(self) -> None:
        """Clear caches and reload data from disk."""
        self._sessions_cache = None
        self._queue_cache = None

    def _load_sessions(self) -> dict[str, Session]:
        if self._sessions_cache is not None:
            return self._sessions_cache
        data = self._read_json(self.sessions_path)
        sessions: dict[str, Session] = {}
        for key, raw in data.get("sessions", {}).items():
            if isinstance(raw, dict):
                sessions[key] = Session.from_dict(key, raw)
        self._sessions_cache = sessions
        return sessions

    def _load_queue(self) -> QueueData:
        if self._queue_cache is not None:
            return self._queue_cache
        data = self._read_json(self.queue_path)
        self._queue_cache = QueueData.from_dict(data)
        return self._queue_cache

    def get_all_sessions(self) -> list[Session]:
        """All sessions sorted by updated_at descending."""
        sessions = list(self._load_sessions().values())
        sessions.sort(key=lambda s: s.updated_at or s.started_at or _EPOCH, reverse=True)
        return sessions

    def get_active_session(self) -> Session | None:
        """Session with status 'running'."""
        for s in self._load_sessions().values():
            if s.status == "running":
                return s
        return None

    def get_recent_sessions(self, limit: int = 10) -> list[Session]:
        """Most recent N sessions sorted by updated_at descending."""
        return self.get_all_sessions()[:limit]

    def get_interrupted_sessions(self) -> list[Session]:
        """Sessions with status 'interrupted'."""
        return [s for s in self._load_sessions().values() if s.status == "interrupted"]

    def get_session(self, key: str) -> Session | None:
        """Get a specific session by key."""
        return self._load_sessions().get(key)

    def get_project_sessions(self, project: str | None = None) -> list[Session]:
        """Sessions for a specific project (or current project)."""
        target = project or self.project_name
        sessions = [
            s for s in self._load_sessions().values()
            if s.project == target
        ]
        sessions.sort(key=lambda s: s.updated_at or s.started_at or _EPOCH, reverse=True)
        return sessions

    def get_queue(self) -> QueueData:
        """Current queue data."""
        return self._load_queue()

    def get_projects_config(self) -> dict[str, Any]:
        """Read projects.json for active project info."""
        projects_path = self.project_path / ".claude" / "data" / "projects.json"
        return self._read_json(projects_path)
