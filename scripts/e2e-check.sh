#!/bin/bash
# e2e-check.sh — E2E test runner with server availability checks
#
# Usage: ./scripts/e2e-check.sh <repo_name> [endpoint] [project_name]
#   repo_name    — repository key from projects.json (e.g., "backend", "frontend")
#   endpoint     — specific API endpoint to test (for API repos, default: health check)
#   project_name — optional, uses active project if omitted
#
# What it does:
#   1. Checks if the server/service is running (prerequisite check)
#   2. If not running — outputs how to start it and exits with clear error
#   3. If running — executes the E2E test command
#   4. Outputs results with actionable hints on failure
#
# Exit codes:
#   0 = E2E tests passed
#   1 = invalid arguments / config error
#   2 = server not running (with start instructions)
#   3 = E2E tests failed

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_NAME="${1:-}"
ENDPOINT="${2:-}"
PROJECT_NAME="${3:-}"

if [ -z "$REPO_NAME" ]; then
    echo "ERROR: Repository name is required" >&2
    echo "HINT: Usage: ./scripts/e2e-check.sh <repo_name> [endpoint] [project]" >&2
    echo "HINT: Example: ./scripts/e2e-check.sh backend /api/users" >&2
    exit 1
fi

# Read project config
CONFIG=$("$SCRIPT_DIR/read-project-config.sh" $PROJECT_NAME 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to read project config" >&2
    exit 1
fi

# Extract E2E config
RESULT=$(python3 -c "
import json, sys

config = json.loads('''$CONFIG''')
repo_name = '$REPO_NAME'

repos = config.get('repositories', {})
if repo_name not in repos:
    available = ', '.join(repos.keys())
    print(f'ERROR: Repository \"{repo_name}\" not found. Available: {available}', file=sys.stderr)
    sys.exit(1)

testing = config.get('testing', {})
if repo_name not in testing:
    print(f'ERROR: No testing config for \"{repo_name}\"', file=sys.stderr)
    print(f'HINT: Add testing.{repo_name} to projects.json', file=sys.stderr)
    sys.exit(1)

test_config = testing[repo_name]
repo_path = repos[repo_name]
test_type = test_config.get('type', '')
base_url = test_config.get('base_url', '')
docker = config.get('docker', {})

e2e_cmd = test_config.get('commands', {}).get('e2e', '')
if e2e_cmd:
    e2e_cmd = e2e_cmd.replace('{{repo}}', repo_path)
    e2e_cmd = e2e_cmd.replace('{{base_url}}', base_url)

print(f'REPO_PATH={repo_path}')
print(f'TEST_TYPE={test_type}')
print(f'BASE_URL={base_url}')
print(f'E2E_CMD={e2e_cmd}')
print(f'DOCKER_START={docker.get(\"start\", \"\")}')
print(f'PROJECT_NAME={config.get(\"name\", \"\")}')
" 2>&1)

if [ $? -ne 0 ]; then
    echo "$RESULT" >&2
    exit 1
fi

eval "$RESULT"

echo "=== E2E Check: $(basename "$REPO_PATH") ($TEST_TYPE) ==="

# Step 1: Check server availability
if [ -n "$BASE_URL" ]; then
    echo "Checking server at $BASE_URL ..."

    if curl -s --max-time 3 --fail "$BASE_URL" > /dev/null 2>&1 || \
       curl -s --max-time 3 "$BASE_URL" 2>/dev/null | head -c 1 | grep -q .; then
        echo "Server: RUNNING"
    else
        echo ""
        echo "ERROR: Server not running at $BASE_URL"
        echo ""
        echo "--- How to Start ---"
        if [ -n "$DOCKER_START" ]; then
            echo "Docker: $DOCKER_START"
        fi
        if [ "$TEST_TYPE" = "api" ]; then
            echo "HINT: Start the backend server manually or via docker"
            echo "HINT: Check if the port is correct in projects.json"
        elif [ "$TEST_TYPE" = "browser" ]; then
            echo "HINT: Start the dev server: cd $REPO_PATH && npm run dev"
            echo "HINT: Or: cd $REPO_PATH && npm start"
        fi
        echo "HINT: After starting, re-run: ./scripts/e2e-check.sh $REPO_NAME"
        exit 2
    fi
fi
echo ""

# Step 2: Run E2E tests
if [ "$TEST_TYPE" = "api" ] && [ -n "$ENDPOINT" ]; then
    # Custom endpoint test
    FULL_URL="${BASE_URL}${ENDPOINT}"
    echo "Testing endpoint: $FULL_URL"
    echo "---"

    RESPONSE=$(curl -s -w "\n---HTTP_CODE:%{http_code}---" "$FULL_URL" 2>&1)
    HTTP_CODE=$(echo "$RESPONSE" | grep -o 'HTTP_CODE:[0-9]*' | cut -d: -f2)
    BODY=$(echo "$RESPONSE" | sed 's/---HTTP_CODE:[0-9]*---//')

    echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
    echo ""
    echo "HTTP Status: $HTTP_CODE"

    if [ -n "$HTTP_CODE" ] && [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 400 ]; then
        echo "STATUS: PASSED"
        exit 0
    else
        echo "STATUS: FAILED"
        echo ""
        echo "--- Troubleshooting ---"
        echo "HINT: Check if the endpoint exists and is correctly routed"
        echo "HINT: Try with auth: curl -s -H 'Authorization: Bearer TOKEN' $FULL_URL"
        echo "HINT: Check server logs for errors"
        exit 3
    fi
elif [ -n "$E2E_CMD" ]; then
    # Run configured E2E command
    echo "Running: $E2E_CMD"
    echo "---"

    eval "$E2E_CMD" 2>&1
    EXIT_CODE=$?

    echo ""
    if [ $EXIT_CODE -eq 0 ]; then
        echo "STATUS: PASSED"
    else
        echo "STATUS: FAILED (exit code: $EXIT_CODE)"
        echo ""
        echo "--- Troubleshooting ---"
        if [ "$TEST_TYPE" = "browser" ]; then
            echo "HINT: Run headed for debugging: cd $REPO_PATH && npx playwright test --headed"
            echo "HINT: Check if browsers are installed: cd $REPO_PATH && npx playwright install"
            echo "HINT: View trace: cd $REPO_PATH && npx playwright show-trace"
        elif [ "$TEST_TYPE" = "api" ]; then
            echo "HINT: Check server logs for 500 errors"
            echo "HINT: Verify test data/fixtures are loaded"
        fi
    fi
    exit $EXIT_CODE
else
    echo "WARNING: No E2E command configured for $REPO_NAME"
    echo "HINT: Add commands.e2e to testing.$REPO_NAME in projects.json"
    exit 1
fi
