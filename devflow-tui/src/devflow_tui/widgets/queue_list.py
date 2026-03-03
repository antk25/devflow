"""Queue list widget for DevFlow TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from ..data.models import QueueData


class QueueList(Widget):
    """Shows queue items with status and a progress bar."""

    DEFAULT_CSS = """
    QueueList {
        height: auto;
        max-height: 8;
        padding: 0 1;
    }
    QueueList .queue-header {
        text-style: bold;
        color: $text;
        height: 1;
    }
    QueueList .queue-item {
        height: 1;
    }
    QueueList .queue-progress {
        height: 1;
        color: $accent;
    }
    QueueList .queue-empty {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, queue_data: QueueData | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._queue = queue_data

    def compose(self) -> ComposeResult:
        yield Static("", id="queue-content")

    def on_mount(self) -> None:
        self._update_content()

    def update_queue(self, queue_data: QueueData) -> None:
        self._queue = queue_data
        self._update_content()

    def _update_content(self) -> None:
        try:
            content = self.query_one("#queue-content", Static)
        except LookupError:
            return

        if not self._queue or not self._queue.items:
            content.update("[dim]Queue empty[/dim]")
            return

        lines: list[str] = []

        # Progress bar
        total = len(self._queue.items)
        done = self._queue.completed_count
        failed = self._queue.failed_count
        running = self._queue.running_item

        if running or done > 0:
            filled = int((done / total) * 30) if total > 0 else 0
            bar = "\u2588" * filled + "\u2591" * (30 - filled)
            lines.append(f"[bold]{bar}[/bold]  {done}/{total}")
            if failed:
                lines[-1] += f" ([red]{failed} failed[/red])"
            lines.append("")

        # Show items (max 5)
        visible = self._queue.items[:5]
        for item in visible:
            icon = item.status_icon
            marker = " \u25b6" if item.status == "running" else ""
            lines.append(
                f"  {icon} #{item.id} /{item.skill}  "
                f"{item.description[:40]}{marker}"
            )

        remaining = total - len(visible)
        if remaining > 0:
            lines.append(f"  [dim]... +{remaining} more[/dim]")

        content.update("\n".join(lines))
