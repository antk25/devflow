"""Phase progress bar widget for DevFlow TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from ..data.models import DISPLAY_PHASES, PHASE_LABELS, Session


class PhaseBar(Widget):
    """Horizontal bar showing phase progress for a session."""

    DEFAULT_CSS = """
    PhaseBar {
        height: auto;
        padding: 0 1;
    }
    PhaseBar .phase-row {
        height: 1;
    }
    PhaseBar .phase-completed {
        color: $success;
    }
    PhaseBar .phase-current {
        color: $warning;
        text-style: bold;
    }
    PhaseBar .phase-skipped {
        color: $text-muted;
    }
    PhaseBar .phase-pending {
        color: $text-disabled;
    }
    """

    def __init__(self, session: Session | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session = session

    def compose(self) -> ComposeResult:
        yield Static(self._render_bar(), classes="phase-row")

    def update_session(self, session: Session | None) -> None:
        self._session = session
        try:
            static = self.query_one(".phase-row", Static)
            static.update(self._render_bar())
        except LookupError:
            pass

    def _render_bar(self) -> str:
        if not self._session:
            return "[dim]No active session[/dim]"

        parts: list[str] = []
        for phase in DISPLAY_PHASES:
            label = PHASE_LABELS.get(phase, phase)
            status = self._session.phase_status(phase)

            if status == "completed":
                parts.append(f"[green]\u2713 {label}[/green]")
            elif status == "current":
                parts.append(f"[yellow bold]\u25b6 {label}[/yellow bold]")
            elif status == "skipped":
                parts.append(f"[dim]\u23e9 {label}[/dim]")
            else:
                parts.append(f"[dim]\u2581 {label}[/dim]")

        return "  ".join(parts)
