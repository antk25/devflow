"""Session details screen for DevFlow TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from rich.markup import escape
from textual.widgets import DataTable, Footer, Header, Static

from ..data.models import PHASE_LABELS, PHASE_ORDER, Session


class SessionDetailsScreen(Screen):
    """Detailed view of a single session."""

    BINDINGS = [
        Binding("escape", "pop_screen", "Back"),
        Binding("q", "pop_screen", "Back"),
    ]

    DEFAULT_CSS = """
    SessionDetailsScreen {
        layout: vertical;
    }
    SessionDetailsScreen .detail-header {
        text-style: bold;
        color: $accent;
        padding: 0 1;
        height: 2;
    }
    SessionDetailsScreen .detail-meta {
        padding: 0 1;
        height: auto;
    }
    SessionDetailsScreen .section-title {
        text-style: bold;
        padding: 1 1 0 1;
        height: 2;
    }
    SessionDetailsScreen .loops-info {
        padding: 0 1;
        height: auto;
    }
    SessionDetailsScreen .phase-data-info {
        padding: 0 1;
        height: auto;
    }
    """

    def __init__(self, session: Session, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session = session

    def compose(self) -> ComposeResult:
        s = self._session
        yield Header()
        with VerticalScroll():
            yield Static(
                f"[bold]{s.status_icon} /{escape(s.skill)}[/bold]  {escape(s.feature)}",
                classes="detail-header",
            )

            # Meta info
            branch = s.work_branch
            started = s.started_at.strftime("%H:%M") if s.started_at else "-"
            meta_lines = [
                f"  Branch: [bold]{branch}[/bold]    "
                f"Started: {started}    "
                f"Duration: {s.duration_display}    "
                f"Status: {s.status}",
            ]
            yield Static("\n".join(meta_lines), classes="detail-meta")

            # Phase table
            yield Static("\u2500\u2500\u2500 Phases", classes="section-title")
            table = DataTable(id="phase-table", cursor_type="none")
            table.add_columns("", "Phase", "Duration", "Result")
            yield table

            # Loops
            yield Static("\u2500\u2500\u2500 Loops", classes="section-title")
            yield Static(self._render_loops(), classes="loops-info")

            # Phase data
            if s.phase_data:
                yield Static("\u2500\u2500\u2500 Phase Data", classes="section-title")
                yield Static(self._render_phase_data(), classes="phase-data-info")

        yield Footer()

    def on_mount(self) -> None:
        self._populate_phases()

    def _populate_phases(self) -> None:
        try:
            table = self.query_one("#phase-table", DataTable)
        except LookupError:
            return

        s = self._session

        # Build a lookup from phase_history
        history_map: dict[str, list] = {}
        for entry in s.phase_history:
            history_map.setdefault(entry.phase, []).append(entry)

        for phase in PHASE_ORDER:
            label = PHASE_LABELS.get(phase, phase)
            status = s.phase_status(phase)

            if status == "completed":
                icon = "[green]\u2713[/green]"
            elif status == "current":
                icon = "[yellow]\u25b6[/yellow]"
            elif status == "skipped":
                icon = "[dim]\u23e9[/dim]"
            else:
                icon = "[dim]\u2581[/dim]"

            # Duration from history
            duration_str = "\u2014"
            result_str = "\u2014"
            entries = history_map.get(phase, [])
            if entries:
                last_entry = entries[-1]
                secs = last_entry.duration_seconds
                if secs < 60:
                    duration_str = f"0:{secs:02d}"
                else:
                    mins = secs // 60
                    remainder = secs % 60
                    duration_str = f"{mins}:{remainder:02d}"
                result_str = last_entry.result
                if last_entry.reason:
                    result_str += f" ({last_entry.reason})"
            elif status == "completed":
                result_str = "success"
            elif status == "current":
                result_str = "in progress"

            table.add_row(icon, label, duration_str, result_str)

    def _render_loops(self) -> str:
        s = self._session
        if not s.loops:
            return "  [dim]No loop data[/dim]"
        parts = []
        for lp in s.loops:
            if lp.attempt > 0:
                parts.append(f"  [yellow]{lp.name}: {lp.attempt}/{lp.max_attempts}[/yellow]")
            else:
                parts.append(f"  [dim]{lp.name}: {lp.attempt}/{lp.max_attempts}[/dim]")
        return "\n".join(parts)

    def _render_phase_data(self) -> str:
        s = self._session
        lines = []
        for phase_key, data in s.phase_data.items():
            label = PHASE_LABELS.get(phase_key, phase_key)
            if isinstance(data, dict):
                for k, v in data.items():
                    val_str = escape(str(v)[:80]) if v else "-"
                    lines.append(f"  [bold]{label}[/bold] / {escape(k)}: {val_str}")
            else:
                lines.append(f"  [bold]{label}[/bold]: {escape(str(data))}")
        return "\n".join(lines) if lines else "  [dim]No phase data[/dim]"
