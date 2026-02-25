#!/bin/bash
# run-tests.sh — Runs tests for a project repository with helpful output
#
# Usage: ./scripts/run-tests.sh <repo_name> [test_type] [filter] [project_name]
#   repo_name    — repository key from projects.json (e.g., "backend", "frontend", "main")
#   test_type    — "unit" (default) or "e2e"
#   filter       — optional test filter (class name, file path, etc.)
#   project_name — optional, uses active project if omitted
#
# Output: Test results to stdout with hints on failure
# Exit codes:
#   0 = tests passed
#   1 = invalid arguments / config error
#   2 = tests failed (with hints)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_NAME="${1:-}"
TEST_TYPE="${2:-unit}"
FILTER="${3:-}"
PROJECT_NAME="${4:-}"

if [ -z "$REPO_NAME" ]; then
    echo "ERROR: Repository name is required" >&2
    echo "HINT: Usage: ./scripts/run-tests.sh <repo_name> [unit|e2e] [filter] [project]" >&2
    echo "HINT: Get repo names: ./scripts/read-project-config.sh | jq '.repositories | keys'" >&2
    exit 1
fi

# Read project config
CONFIG=$("$SCRIPT_DIR/read-project-config.sh" $PROJECT_NAME 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to read project config" >&2
    echo "HINT: Check that project is registered and active" >&2
    exit 1
fi

# Extract test command and repo path
RESULT=$(python3 -c "
import json, sys

config = json.loads('''$CONFIG''')
repo_name = '$REPO_NAME'
test_type = '$TEST_TYPE'
filter_arg = '$FILTER'

# Get repo path
repos = config.get('repositories', {})
if repo_name not in repos:
    available = ', '.join(repos.keys())
    print(f'ERROR: Repository \"{repo_name}\" not found. Available: {available}', file=sys.stderr)
    sys.exit(1)
repo_path = repos[repo_name]

# Get test config
testing = config.get('testing', {})
if repo_name not in testing:
    print(f'ERROR: No testing config for \"{repo_name}\"', file=sys.stderr)
    print(f'HINT: Add testing config to projects.json under testing.{repo_name}', file=sys.stderr)
    sys.exit(1)

test_config = testing[repo_name]
commands = test_config.get('commands', {})
if test_type not in commands:
    available = ', '.join(commands.keys())
    print(f'ERROR: No \"{test_type}\" test command for \"{repo_name}\". Available: {available}', file=sys.stderr)
    sys.exit(1)

# Build command with substitutions
cmd = commands[test_type]
cmd = cmd.replace('{{repo}}', repo_path)
base_url = test_config.get('base_url', '')
cmd = cmd.replace('{{base_url}}', base_url)

print(f'REPO_PATH={repo_path}')
print(f'TEST_CMD={cmd}')
print(f'TEST_TYPE_CONFIG={test_config.get(\"type\", \"\")}')
print(f'BASE_URL={base_url}')
" 2>&1)

if [ $? -ne 0 ]; then
    echo "$RESULT" >&2
    exit 1
fi

eval "$RESULT"

echo "=== Running $TEST_TYPE tests: $(basename "$REPO_PATH") ==="
echo "Command: $TEST_CMD"
if [ -n "$FILTER" ]; then
    echo "Filter: $FILTER"
fi
echo "---"

# Build final command with filter
FINAL_CMD="$TEST_CMD"
if [ -n "$FILTER" ]; then
    # Detect test framework and apply filter appropriately
    if echo "$FINAL_CMD" | grep -q "phpunit"; then
        FINAL_CMD="$FINAL_CMD --filter $FILTER"
    elif echo "$FINAL_CMD" | grep -q "mvnw test\|maven"; then
        FINAL_CMD="$FINAL_CMD -Dtest=$FILTER"
    elif echo "$FINAL_CMD" | grep -q "npm test\|jest\|vitest"; then
        FINAL_CMD="$FINAL_CMD -- --testPathPattern=$FILTER"
    elif echo "$FINAL_CMD" | grep -q "playwright"; then
        FINAL_CMD="$FINAL_CMD $FILTER"
    fi
fi

# Run tests
eval "$FINAL_CMD" 2>&1
EXIT_CODE=$?

echo ""
echo "=== Test Results ==="

if [ $EXIT_CODE -eq 0 ]; then
    echo "STATUS: PASSED"
else
    echo "STATUS: FAILED (exit code: $EXIT_CODE)"
    echo ""
    echo "--- Troubleshooting Hints ---"

    # Framework-specific hints
    if echo "$FINAL_CMD" | grep -q "phpunit"; then
        echo "HINT: Run single test: cd $REPO_PATH && ./vendor/bin/phpunit --filter TestMethodName"
        echo "HINT: Run with verbose: cd $REPO_PATH && ./vendor/bin/phpunit -v --filter TestClassName"
        echo "HINT: Check for missing dependencies: cd $REPO_PATH && composer install"
    elif echo "$FINAL_CMD" | grep -q "mvnw"; then
        echo "HINT: Run single test: cd $REPO_PATH && ./mvnw test -Dtest=TestClassName"
        echo "HINT: Skip tests temporarily: cd $REPO_PATH && ./mvnw compile -DskipTests"
        echo "HINT: Check Java version: java -version"
    elif echo "$FINAL_CMD" | grep -q "npm test\|jest\|vitest"; then
        echo "HINT: Run single test: cd $REPO_PATH && npm test -- --testPathPattern=filename"
        echo "HINT: Run with verbose: cd $REPO_PATH && npm test -- --verbose"
        echo "HINT: Check for missing deps: cd $REPO_PATH && npm install"
    elif echo "$FINAL_CMD" | grep -q "playwright"; then
        echo "HINT: Run headed: cd $REPO_PATH && npx playwright test --headed"
        echo "HINT: Debug mode: cd $REPO_PATH && npx playwright test --debug"
        echo "HINT: Install browsers: cd $REPO_PATH && npx playwright install"
    fi

    echo "HINT: Check test output above for specific assertion failures"
fi

exit $EXIT_CODE
