#!/bin/bash
# git-context.sh — Outputs git history, branches, and commit style for a repository
#
# Usage: ./scripts/git-context.sh <repo_path> [commit_count]
#   repo_path    — absolute path to git repository
#   commit_count — number of recent commits to show (default: 20)
#
# Output: Structured text to stdout with recent commits, branches, and commit style analysis
# Exit codes:
#   0 = success
#   1 = invalid arguments
#   2 = not a git repository

set -euo pipefail

REPO_PATH="${1:-}"
COMMIT_COUNT="${2:-20}"

if [ -z "$REPO_PATH" ]; then
    echo "ERROR: Repository path is required" >&2
    echo "HINT: Usage: ./scripts/git-context.sh <repo_path> [commit_count]" >&2
    echo "HINT: Get repo paths from: ./scripts/read-project-config.sh | jq '.repositories'" >&2
    exit 1
fi

if [ ! -d "$REPO_PATH/.git" ]; then
    echo "ERROR: Not a git repository: $REPO_PATH" >&2
    echo "HINT: Check the path — it should point to the root of a git repo" >&2
    echo "HINT: For multi-repo projects, use the specific repo path (backend/frontend), not the project root" >&2
    exit 2
fi

echo "=== Git Context: $(basename "$REPO_PATH") ==="
echo "Path: $REPO_PATH"
echo ""

# Current branch
echo "--- Current Branch ---"
git -C "$REPO_PATH" branch --show-current 2>/dev/null || echo "(detached HEAD)"
echo ""

# Recent commits
echo "--- Recent Commits (last $COMMIT_COUNT) ---"
git -C "$REPO_PATH" log --oneline -"$COMMIT_COUNT" 2>/dev/null || echo "(no commits)"
echo ""

# Local branches
echo "--- Local Branches ---"
git -C "$REPO_PATH" branch --list 2>/dev/null | head -20
echo ""

# Working tree status (short)
echo "--- Working Tree ---"
DIRTY=$(git -C "$REPO_PATH" status --porcelain 2>/dev/null | head -10)
if [ -z "$DIRTY" ]; then
    echo "Clean"
else
    echo "$DIRTY"
    TOTAL=$(git -C "$REPO_PATH" status --porcelain 2>/dev/null | wc -l)
    if [ "$TOTAL" -gt 10 ]; then
        echo "... and $((TOTAL - 10)) more files"
    fi
fi
echo ""

# Commit style analysis
echo "--- Commit Style Analysis ---"
python3 -c "
import subprocess, re, collections

result = subprocess.run(
    ['git', '-C', '$REPO_PATH', 'log', '--oneline', '-50', '--format=%s'],
    capture_output=True, text=True
)
messages = [m for m in result.stdout.strip().split('\n') if m]

if not messages:
    print('No commits to analyze')
    exit()

patterns = {
    'conventional': r'^(feat|fix|refactor|test|docs|chore|style|perf|ci|build|revert)(\(.+\))?[!]?:\s',
    'ticket_prefix': r'^[A-Z]+-\d+[\s:]',
    'capitalized': r'^[A-Z][a-z]',
}

counts = {}
for name, pattern in patterns.items():
    counts[name] = sum(1 for m in messages if re.match(pattern, m))

total = len(messages)
dominant = max(counts, key=counts.get)
confidence = counts[dominant] / total * 100

# Detect language
ru_count = sum(1 for m in messages if any(ord(c) > 1024 for c in m))
lang = 'ru' if ru_count > total * 0.5 else 'en'

print(f'Total analyzed: {total} commits')
print(f'Dominant style: {dominant} ({counts[dominant]}/{total}, {confidence:.0f}%)')
print(f'Language: {lang}')
print(f'Breakdown: ' + ', '.join(f'{k}={v}' for k, v in counts.items()))

# Show top 3 examples of dominant style
examples = [m for m in messages if re.match(patterns[dominant], m)][:3]
if examples:
    print(f'Examples:')
    for ex in examples:
        print(f'  - {ex}')
" 2>/dev/null || echo "HINT: python3 required for commit style analysis"
