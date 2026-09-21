#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
DEVFLOW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$DEVFLOW_DIR/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3
if ! "$PYTHON" -c 'import yaml' 2>/dev/null; then
    echo 'Missing PyYAML; run ./install.sh first.' >&2
    exit 1
fi
exec "$PYTHON" "$DEVFLOW_DIR/scripts/launch.py" "$@"
