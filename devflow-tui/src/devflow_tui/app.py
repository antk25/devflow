"""DevFlow TUI application entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from textual.app import App

from .data.reader import DevFlowData
from .screens.dashboard import DashboardScreen


class DevFlowTUI(App):
    """Terminal monitor for DevFlow sessions and queue."""

    TITLE = "DevFlow Monitor"
    CSS_PATH = "styles/theme.tcss"

    def __init__(self, data: DevFlowData, **kwargs) -> None:
        super().__init__(**kwargs)
        self._data = data

    def on_mount(self) -> None:
        self.push_screen(DashboardScreen(self._data))


def _find_devflow_root() -> Path | None:
    """Find DevFlow project root by walking up from cwd."""
    # Walk up from current directory
    current = Path.cwd()
    for p in [current, *current.parents]:
        if (p / ".claude" / "data" / "sessions.json").exists():
            return p
    return None


def _get_project_name(root: Path) -> str:
    """Read active project name from projects.json."""
    projects_path = root / ".claude" / "data" / "projects.json"
    if projects_path.exists():
        import json

        try:
            with open(projects_path) as f:
                data = json.load(f)
            return data.get("active", "")
        except (json.JSONDecodeError, OSError):
            pass
    return ""


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="devflow-tui",
        description="TUI monitor for DevFlow sessions and queue",
    )
    parser.add_argument(
        "--project",
        help="Project name to filter sessions",
    )
    parser.add_argument(
        "--path",
        help="Path to DevFlow project root",
    )
    args = parser.parse_args()

    # Find project root
    if args.path:
        root = Path(args.path)
    else:
        root = _find_devflow_root()

    if not root or not (root / ".claude" / "data" / "sessions.json").exists():
        print(
            "ERROR: Could not find DevFlow project root.\n"
            "HINT: Run from the devflow directory or use --path",
            file=sys.stderr,
        )
        sys.exit(1)

    project_name = args.project or _get_project_name(root)

    data = DevFlowData(str(root), project_name)
    app = DevFlowTUI(data)
    app.run()


if __name__ == "__main__":
    main()
