#!/bin/bash
# test-reaction.sh — Post-commit test runner with structured output
#
# Usage: ./scripts/test-reaction.sh <repo_name> [filter] [project_name]
#   repo_name    — repository key from projects.json (e.g., "backend", "frontend", "main")
#   filter       — optional test filter (class name, file path, etc.)
#   project_name — optional, uses active project if omitted
#
# Wraps run-tests.sh with structured output for the test reaction loop.
#
# Output format:
#   TEST_REACTION: PASSED|FAILED
#   OUTPUT_HASH: <md5 of test output, for loop detection>
#   DURATION: <seconds>
#   <test output follows>
#
# Exit codes:
#   0 = tests passed
#   1 = invalid arguments / config error
#   2 = tests failed

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_NAME="${1:-}"
FILTER="${2:-}"
PROJECT_NAME="${3:-}"

if [ -z "$REPO_NAME" ]; then
    echo "ERROR: Repository name is required" >&2
    echo "HINT: Usage: ./scripts/test-reaction.sh <repo_name> [filter] [project_name]" >&2
    exit 1
fi

START_TIME=$(date +%s)

# Run tests and capture output
TEST_OUTPUT=$("$SCRIPT_DIR/run-tests.sh" "$REPO_NAME" unit "$FILTER" "$PROJECT_NAME" 2>&1)
TEST_EXIT=$?

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# Compute output hash for loop detection
OUTPUT_HASH=$(echo "$TEST_OUTPUT" | md5sum | cut -d' ' -f1)

# Structured header
if [ $TEST_EXIT -eq 0 ]; then
    echo "TEST_REACTION: PASSED"
else
    echo "TEST_REACTION: FAILED"
fi
echo "OUTPUT_HASH: $OUTPUT_HASH"
echo "DURATION: ${DURATION}s"
echo "---"

# Full test output
echo "$TEST_OUTPUT"

if [ $TEST_EXIT -eq 0 ]; then
    exit 0
else
    exit 2
fi
