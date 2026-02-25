#!/bin/bash
# check-loop.sh — Detects loops in retry cycles via diff/output hashes
#
# Usage: ./scripts/check-loop.sh <branch> <loop_name> <hash>
#   branch    — session key (work branch name)
#   loop_name — loop identifier (arch_validation, review_fix, test_fix)
#   hash      — md5 hash of current diff/output to check for repetition
#
# Output to stdout (machine-readable decision):
#   CONTINUE       — no loop, attempt recorded, continue retrying
#   LOOP_DETECTED  — same hash seen before, try fundamentally different approach
#   GIVE_UP        — max attempts reached, stop retrying
#
# Additional context printed to stderr for the agent.
#
# Exit codes:
#   0 = CONTINUE (safe to retry)
#   1 = invalid arguments / session error
#   2 = LOOP_DETECTED
#   3 = GIVE_UP

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$SCRIPT_DIR")"
SESSIONS_FILE="$DEVFLOW_DIR/.claude/data/sessions.json"

BRANCH="${1:-}"
LOOP_NAME="${2:-}"
HASH="${3:-}"

if [ -z "$BRANCH" ] || [ -z "$LOOP_NAME" ] || [ -z "$HASH" ]; then
    echo "ERROR: All arguments are required" >&2
    echo "HINT: Usage: ./scripts/check-loop.sh <branch> <loop_name> <hash>" >&2
    echo "HINT: Generate hash: git diff --stat | md5sum | cut -d' ' -f1" >&2
    echo "HINT: Loop names: arch_validation, review_fix, test_fix" >&2
    exit 1
fi

if [ ! -f "$SESSIONS_FILE" ]; then
    echo "ERROR: sessions.json not found" >&2
    exit 1
fi

python3 -c "
import json, sys

with open('$SESSIONS_FILE') as f:
    data = json.load(f)

branch = '$BRANCH'
loop_name = '$LOOP_NAME'
new_hash = '$HASH'

session = data.get('sessions', {}).get(branch)
if not session:
    print(f'ERROR: Session \"{branch}\" not found', file=sys.stderr)
    sys.exit(1)

loops = session.get('loops', {})
if loop_name not in loops:
    print(f'ERROR: Loop \"{loop_name}\" not found in session', file=sys.stderr)
    print(f'HINT: Valid loops: {list(loops.keys())}', file=sys.stderr)
    sys.exit(1)

loop = loops[loop_name]
attempt = loop.get('attempt', 0)
max_attempts = loop.get('max_attempts', 3)
diff_hashes = loop.get('diff_hashes', [])
failures = loop.get('failures', [])

# Check max attempts
if attempt >= max_attempts:
    print('GIVE_UP')
    print(f'Max attempts ({max_attempts}) reached for {loop_name}', file=sys.stderr)
    print(f'Previous failures:', file=sys.stderr)
    for f in failures:
        print(f'  - {f}', file=sys.stderr)
    print(f'HINT: Consider skipping this validation or fixing manually', file=sys.stderr)
    sys.exit(3)

# Check for loop (same hash seen before)
if new_hash in diff_hashes:
    print('LOOP_DETECTED')
    print(f'Hash {new_hash[:8]}... was already seen in attempt #{diff_hashes.index(new_hash) + 1}', file=sys.stderr)
    print(f'The fix is producing identical changes — need a fundamentally different approach', file=sys.stderr)
    print(f'Previous failures:', file=sys.stderr)
    for f in failures:
        print(f'  - {f}', file=sys.stderr)
    # Still record the attempt
    loop['attempt'] = attempt + 1
    data['sessions'][branch]['loops'][loop_name] = loop
    with open('$SESSIONS_FILE', 'w') as f_out:
        json.dump(data, f_out, indent=2, ensure_ascii=False)
        f_out.write('\n')
    sys.exit(2)

# No loop — record and continue
loop['attempt'] = attempt + 1
loop['diff_hashes'].append(new_hash)
data['sessions'][branch]['loops'][loop_name] = loop

with open('$SESSIONS_FILE', 'w') as f_out:
    json.dump(data, f_out, indent=2, ensure_ascii=False)
    f_out.write('\n')

print('CONTINUE')
print(f'Attempt {attempt + 1}/{max_attempts} for {loop_name}', file=sys.stderr)
print(f'Hash {new_hash[:8]}... recorded', file=sys.stderr)
"
