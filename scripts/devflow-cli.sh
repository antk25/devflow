#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
DEVFLOW_DIR="$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")"
PYTHON="$DEVFLOW_DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3
exec "$PYTHON" "$DEVFLOW_DIR/scripts/devflow_cli.py" "$@"
