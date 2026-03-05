#!/bin/bash
# resolve-agent.sh — Resolves project-specific agent file for a given role
#
# Usage: ./scripts/resolve-agent.sh <project_path> <agent_type>
#   agent_type: "JS Developer", "PHP Developer", "Code Reviewer",
#               "Architecture Guardian", "Tester"
#
# Resolution order (first found wins):
#   1. <project>/.claude/agents/<specific>.md  (e.g., js-developer.md, php-developer.md)
#   2. <project>/.claude/agents/developer.md   (generic developer)
#   3. (empty — no project agent, use default)
#
# Output: path to agent file, or empty string if none found
# Exit codes: 0 = found, 1 = not found

set -euo pipefail

PROJECT_PATH="${1:?Usage: resolve-agent.sh <project_path> <agent_type>}"
AGENT_TYPE="${2:?Usage: resolve-agent.sh <project_path> <agent_type>}"
AGENTS_DIR="$PROJECT_PATH/.claude/agents"

if [ ! -d "$AGENTS_DIR" ]; then
    exit 1
fi

# Map agent type to filename candidates
case "$AGENT_TYPE" in
    "JS Developer")
        CANDIDATES=("js-developer.md" "developer.md")
        ;;
    "PHP Developer")
        CANDIDATES=("php-developer.md" "developer.md")
        ;;
    "Code Reviewer")
        CANDIDATES=("reviewer.md")
        ;;
    "Architecture Guardian")
        CANDIDATES=("architecture-guardian.md")
        ;;
    "Tester")
        CANDIDATES=("tester.md")
        ;;
    *)
        # Unknown type — try kebab-case of the name, then developer.md
        KEBAB=$(echo "$AGENT_TYPE" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
        CANDIDATES=("${KEBAB}.md" "developer.md")
        ;;
esac

for candidate in "${CANDIDATES[@]}"; do
    if [ -f "$AGENTS_DIR/$candidate" ]; then
        echo "$AGENTS_DIR/$candidate"
        exit 0
    fi
done

exit 1
