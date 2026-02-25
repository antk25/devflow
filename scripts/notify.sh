#!/bin/bash
# notify.sh — Desktop notification (best-effort)
#
# Usage: ./scripts/notify.sh <title> <body> [urgency] [icon]
#   title   — notification title (default: "Orchestrator")
#   body    — notification body
#   urgency — low, normal, critical (default: normal)
#   icon    — icon name (default: dialog-information)
#
# Best-effort — silently exits if notify-send unavailable.
# Exit codes: always 0

TITLE="${1:-Orchestrator}"
BODY="${2:-}"
URGENCY="${3:-normal}"
ICON="${4:-dialog-information}"

if ! command -v notify-send &>/dev/null; then exit 0; fi
notify-send -u "$URGENCY" -i "$ICON" "$TITLE" "$BODY" 2>/dev/null || true
