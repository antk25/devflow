#!/usr/bin/env bash
set -euo pipefail
DEVFLOW_DIR="$(dirname "$(dirname "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")")")"
[ -f AGENTS.md ] || exit 0
printf 'PROJECT_RESTORE\n'
"$DEVFLOW_DIR/scripts/devflow-cli.sh" context
printf 'OBSIDIAN_CONTEXT\n'
"$DEVFLOW_DIR/scripts/devflow-cli.sh" active
