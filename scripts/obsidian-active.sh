#!/usr/bin/env bash
# Shared read-only routing; malformed metadata is reported, never silently discarded.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[ -f AGENTS.md ] || exit 0
exec "$SCRIPT_DIR/devflow-cli.sh" active "$@"
