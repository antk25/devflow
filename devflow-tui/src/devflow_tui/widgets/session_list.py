"""Session list widget for DevFlow TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

from ..data.models import Session


class SessionList(Widget):
    """List of recent sessions with status icons."""

    DEFAULT_CSS = """
    SessionList {
        height: auto;
        max-height: 12;
    }
    SessionList DataTable {
        height: auto;
        max-height: 11;
    }
    """

    class Selected(Message):
        """Posted when a session is selected."""

        def __init__(self, session_key: str) -> None:
            super().__init__()
            self.session_key = session_key

    def __init__(self, sessions: list[Session] | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions = sessions or []
        self._key_map: dict[int, str] = {}

    def compose(self) -> ComposeResult:
        table = DataTable(cursor_type="row", zebra_stripes=True)
        table.add_columns("", "Skill", "Feature", "Duration", "Status")
        yield table

    def on_mount(self) -> None:
        self._populate()

    def update_sessions(self, sessions: list[Session]) -> None:
        self._sessions = sessions
        self._populate()

    def _populate(self) -> None:
        try:
            table = self.query_one(DataTable)
        except LookupError:
            return
        table.clear()
        self._key_map.clear()

        for i, s in enumerate(self._sessions):
            time_str = ""
            if s.started_at:
                time_str = s.started_at.strftime("%H:%M")
            feature = s.feature[:50] if s.feature else ""
            table.add_row(
                s.status_icon,
                f"/{s.skill}",
                feature,
                s.duration_display,
                s.status,
                key=str(i),
            )
            self._key_map[i] = s.key

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value is not None:
            idx = int(event.row_key.value)
            session_key = self._key_map.get(idx)
            if session_key:
                self.post_message(self.Selected(session_key))
