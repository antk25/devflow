#!/bin/bash
# session-checkpoint.sh — Updates session phase in sessions.json
#
# Usage: ./scripts/session-checkpoint.sh <branch> <new_phase> [phase_data_key=value ...]
#   branch     — session key (work branch name, e.g., "DEV-501-work")
#   new_phase  — phase to set as current (e.g., "phase_3_implement")
#   phase_data — optional key=value pairs to store in phase_data
#
# Special keys:
#   result=<success|warning|skipped|failed>  — phase completion result (stored in phase_history)
#   reason=<text>                            — reason for non-success result (stored in phase_history)
#
# What it does:
#   1. Reads sessions.json
#   2. Moves current_phase to completed_phases
#   3. Sets new current_phase
#   4. Updates updated_at timestamp
#   5. Optionally stores phase_data
#   6. Appends entry to phase_history (with result/reason if provided)
#
# Output: Updated session summary to stdout
# Exit codes:
#   0 = success
#   1 = invalid arguments
#   2 = session not found
#   4 = contract gate blocked (phase_2.5 not completed before phase_3)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR_DIR="$(dirname "$SCRIPT_DIR")"
SESSIONS_FILE="$ORCHESTRATOR_DIR/.claude/data/sessions.json"

BRANCH="${1:-}"
NEW_PHASE="${2:-}"
shift 2 2>/dev/null || true

if [ -z "$BRANCH" ] || [ -z "$NEW_PHASE" ]; then
    echo "ERROR: Branch and new_phase are required" >&2
    echo "HINT: Usage: ./scripts/session-checkpoint.sh <branch> <new_phase> [key=value ...]" >&2
    echo "HINT: Example: ./scripts/session-checkpoint.sh DEV-501-work phase_3_implement plan_summary='Add auth'" >&2
    echo "HINT: Special keys: result=success|warning|skipped|failed reason='explanation'" >&2
    exit 1
fi

if [ ! -f "$SESSIONS_FILE" ]; then
    echo "ERROR: sessions.json not found at $SESSIONS_FILE" >&2
    echo "HINT: Session must be initialized first (Phase 0 of /develop, /fix, /refactor)" >&2
    exit 1
fi

# Collect phase_data key=value pairs, extract result/reason separately
PHASE_DATA_JSON="{}"
RESULT_VALUE=""
REASON_VALUE=""
for arg in "$@"; do
    if echo "$arg" | grep -q '='; then
        KEY=$(echo "$arg" | cut -d= -f1)
        VALUE=$(echo "$arg" | cut -d= -f2-)
        if [ "$KEY" = "result" ]; then
            RESULT_VALUE="$VALUE"
        elif [ "$KEY" = "reason" ]; then
            REASON_VALUE="$VALUE"
        else
            PHASE_DATA_JSON=$(echo "$PHASE_DATA_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
d['$KEY'] = '$VALUE'
json.dump(d, sys.stdout)
")
        fi
    fi
done

python3 -c "
import json, sys
from datetime import datetime, timezone

with open('$SESSIONS_FILE') as f:
    data = json.load(f)

branch = '$BRANCH'
new_phase = '$NEW_PHASE'
result_value = '$RESULT_VALUE'
reason_value = '$REASON_VALUE'
phase_data_json = json.loads('$(echo "$PHASE_DATA_JSON" | sed "s/'/\\\\'/g")')

sessions = data.get('sessions', {})
if branch not in sessions:
    available = ', '.join(list(sessions.keys())[-5:])
    print(f'ERROR: Session \"{branch}\" not found', file=sys.stderr)
    print(f'HINT: Recent sessions: {available}', file=sys.stderr)
    sys.exit(2)

session = sessions[branch]
old_phase = session.get('current_phase', '')
now = datetime.now(timezone.utc).isoformat()

# CONTRACT GATE: Block transition to phase_3_implement if contract was required but skipped
if new_phase == 'phase_3_implement':
    completed = session.get('completed_phases', [])
    # Check if contract phase was completed or explicitly skipped
    contract_done = 'phase_2.5_contract' in completed
    contract_skipped = session.get('phase_data', {}).get('phase_2.5_contract', {}).get('decision') == 'CONTRACT_SKIP'
    if not contract_done and not contract_skipped:
        print('ERROR: Cannot transition to phase_3_implement — contract phase not completed', file=sys.stderr)
        print('HINT: Run ./scripts/require-contract.sh <branch> \"<plan_summary>\" first', file=sys.stderr)
        print('HINT: If contract is not needed, run checkpoint for phase_2.5_contract with decision=CONTRACT_SKIP', file=sys.stderr)
        sys.exit(4)

# Move old phase to completed
completed = session.get('completed_phases', [])
if old_phase and old_phase not in completed:
    completed.append(old_phase)
session['completed_phases'] = completed

# Set new phase
session['current_phase'] = new_phase
session['updated_at'] = now

# Store phase data
if phase_data_json:
    if 'phase_data' not in session:
        session['phase_data'] = {}
    if old_phase not in session['phase_data']:
        session['phase_data'][old_phase] = {}
    session['phase_data'][old_phase].update(phase_data_json)

# Build phase_history entry for the completed phase
if old_phase:
    if 'phase_history' not in session:
        session['phase_history'] = []

    # Calculate duration from previous entry's completed_at (or started_at for first)
    duration_seconds = 0
    if session['phase_history']:
        prev_completed = session['phase_history'][-1].get('completed_at', '')
        if prev_completed:
            try:
                prev_dt = datetime.fromisoformat(prev_completed)
                now_dt = datetime.fromisoformat(now)
                duration_seconds = int((now_dt - prev_dt).total_seconds())
            except (ValueError, TypeError):
                pass
    else:
        started_at = session.get('started_at', '')
        if started_at:
            try:
                start_dt = datetime.fromisoformat(started_at)
                now_dt = datetime.fromisoformat(now)
                duration_seconds = int((now_dt - start_dt).total_seconds())
            except (ValueError, TypeError):
                pass

    entry = {
        'phase': old_phase,
        'completed_at': now,
        'duration_seconds': max(duration_seconds, 0),
        'result': result_value or 'success',
        'reason': reason_value
    }
    session['phase_history'].append(entry)

data['sessions'][branch] = session

with open('$SESSIONS_FILE', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write('\n')

# Output summary
print(f'CHECKPOINT: {branch}')
print(f'  {old_phase} -> {new_phase}')
print(f'  Completed: {len(completed)} phases')
if phase_data_json:
    for k, v in phase_data_json.items():
        val_str = str(v)[:80]
        print(f'  Data: {k}={val_str}')
if result_value:
    reason_str = f' ({reason_value})' if reason_value else ''
    print(f'  Result: {result_value}{reason_str}')
"
