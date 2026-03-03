"""Dashboard screen — main view of DevFlow TUI."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Rule, Static

from ..data.models import Session
from ..data.reader import DevFlowData
from ..widgets.phase_bar import PhaseBar
from ..widgets.queue_list import QueueList
from ..widgets.session_list import SessionList


class ActiveSessionPanel(Vertical):
    """Panel showing the currently running session."""

    DEFAULT_CSS = """
    ActiveSessionPanel {
        height: auto;
        padding: 0 1;
    }
    ActiveSessionPanel .session-title {
        text-style: bold;
        color: $accent;
        height: 1;
    }
    ActiveSessionPanel .session-meta {
        color: $text;
        height: 1;
    }
    """

    def __init__(self, session: Session | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session = session

    def compose(self) -> ComposeResult:
        yield Static("", id="active-title", classes="session-title")
        yield PhaseBar(self._session, id="phase-bar")
        yield Static("", id="active-meta", classes="session-meta")

    def on_mount(self) -> None:
        self._update_content()

    def update_session(self, session: Session | None) -> None:
        self._session = session
        self._update_content()
        try:
            bar = self.query_one("#phase-bar", PhaseBar)
            bar.update_session(session)
        except LookupError:
            pass

    def _update_content(self) -> None:
        s = self._session
        try:
            title_w = self.query_one("#active-title", Static)
            meta_w = self.query_one("#active-meta", Static)
        except LookupError:
            return

        if not s:
            title_w.update("[dim]No active session[/dim]")
            meta_w.update("")
            return

        title_w.update(
            f"\u25b6 [bold]{s.status.upper()}:[/bold] "
            f"/{escape(s.skill)} {escape(s.feature)}"
        )

        parts: list[str] = []
        parts.append(f"Duration: {s.duration_display}")
        parts.append(f"Phase: {s.current_phase_label}")

        active_loops = [
            lp for lp in s.loops if lp.attempt > 0
        ]
        if active_loops:
            loop_strs = [f"{lp.name}: {lp.attempt}/{lp.max_attempts}" for lp in active_loops]
            parts.append(f"Loops: {', '.join(loop_strs)}")
        else:
            parts.append("Loops: 0")

        meta_w.update("  |  ".join(parts))


class DashboardScreen(Screen):
    """Main dashboard screen."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("f5", "refresh", "Refresh"),
        Binding("d", "details", "Details", show=True),
    ]

    DEFAULT_CSS = """
    DashboardScreen {
        layout: vertical;
    }
    DashboardScreen .section-label {
        text-style: bold;
        color: $text;
        padding: 0 1;
        height: 1;
        margin-top: 1;
    }
    """

    def __init__(self, data: DevFlowData, **kwargs) -> None:
        super().__init__(**kwargs)
        self._data = data

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield ActiveSessionPanel(id="active-panel")
            yield Rule()
            yield Static("\u2500\u2500\u2500 Queue", classes="section-label")
            yield QueueList(id="queue-list")
            yield Rule()
            yield Static("\u2500\u2500\u2500 Recent Sessions", classes="section-label")
            yield SessionList(id="session-list")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_data()
        self.set_interval(2.0, self._auto_refresh)

    def _auto_refresh(self) -> None:
        self._data.reload()
        self._refresh_data()

    def action_refresh(self) -> None:
        self._data.reload()
        self._refresh_data()
        self.notify("Refreshed", timeout=1)

    def action_details(self) -> None:
        active = self._data.get_active_session()
        if active:
            from .details import SessionDetailsScreen

            self.app.push_screen(SessionDetailsScreen(active))
        else:
            self.notify("No active session", severity="warning", timeout=2)

    def on_session_list_selected(self, event: SessionList.Selected) -> None:
        session = self._data.get_session(event.session_key)
        if session:
            from .details import SessionDetailsScreen

            self.app.push_screen(SessionDetailsScreen(session))

    def _refresh_data(self) -> None:
        active = self._data.get_active_session()
        recent = self._data.get_recent_sessions(limit=5)
        queue = self._data.get_queue()

        try:
            panel = self.query_one("#active-panel", ActiveSessionPanel)
            panel.update_session(active)
        except LookupError:
            pass

        try:
            session_list = self.query_one("#session-list", SessionList)
            session_list.update_sessions(recent)
        except LookupError:
            pass

        try:
            queue_list = self.query_one("#queue-list", QueueList)
            queue_list.update_queue(queue)
        except LookupError:
            pass
