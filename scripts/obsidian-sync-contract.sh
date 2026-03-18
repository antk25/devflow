#!/bin/bash
# obsidian-sync-contract.sh — Update contract in Obsidian after implementation changes
#
# Usage: obsidian-sync-contract.sh <contract_path> <action> [args...]
#
# Actions:
#   status <new_status>     — Update frontmatter status (draft|approved|in_review|completed)
#   changelog <description> — Append entry to ## Changelog section
#   section <name> <file>   — Replace a section (## <name>) with content from file
#   diff                    — Show sections that may need updating (reads contract, outputs section names)
#
# Exit codes:
#   0 = success
#   1 = contract file not found
#   2 = invalid arguments

set -euo pipefail

CONTRACT_PATH="${1:-}"
ACTION="${2:-}"

if [ -z "$CONTRACT_PATH" ] || [ -z "$ACTION" ]; then
    echo "ERROR: Required: contract_path, action" >&2
    echo "HINT: Usage: obsidian-sync-contract.sh <path> status|changelog|section|diff [args]" >&2
    exit 2
fi

if [ ! -f "$CONTRACT_PATH" ]; then
    echo "ERROR: Contract file not found: $CONTRACT_PATH" >&2
    exit 1
fi

case "$ACTION" in
    status)
        NEW_STATUS="${3:-}"
        if [ -z "$NEW_STATUS" ]; then
            echo "ERROR: status requires a value (draft|approved|in_review|completed)" >&2
            exit 2
        fi
        python3 -c "
import re, sys

path = '$CONTRACT_PATH'
status = '$NEW_STATUS'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Update status in frontmatter
content = re.sub(r'^(status:\s*).*$', f'\\1{status}', content, count=1, flags=re.MULTILINE)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print(f'Status updated to: {status}')
"
        ;;

    changelog)
        DESCRIPTION="${3:-}"
        if [ -z "$DESCRIPTION" ]; then
            echo "ERROR: changelog requires a description" >&2
            exit 2
        fi
        python3 -c "
import sys
from datetime import date

path = '$CONTRACT_PATH'
desc = '''$DESCRIPTION'''

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

changelog_entry = f'- **{date.today()}:** {desc}'

# Find or create ## Changelog section
if '## Changelog' in content:
    # Append after the ## Changelog header
    parts = content.split('## Changelog', 1)
    # Find end of section (next ## or end of file)
    rest = parts[1]
    lines = rest.split('\n')
    insert_idx = 1  # after the header line
    for i, line in enumerate(lines[1:], 1):
        if line.startswith('## ') and not line.startswith('## Changelog'):
            insert_idx = i
            break
        insert_idx = i + 1
    lines.insert(insert_idx, changelog_entry)
    content = parts[0] + '## Changelog' + '\n'.join(lines)
else:
    # Add Changelog section before the last ---
    content = content.rstrip() + '\n\n---\n\n## Changelog\n\n' + changelog_entry + '\n'

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print(f'Changelog entry added')
"
        ;;

    section)
        SECTION_NAME="${3:-}"
        SECTION_FILE="${4:-}"
        if [ -z "$SECTION_NAME" ] || [ -z "$SECTION_FILE" ]; then
            echo "ERROR: section requires name and content file" >&2
            exit 2
        fi
        python3 -c "
import re, sys

path = '$CONTRACT_PATH'
section_name = '$SECTION_NAME'
section_file = '$SECTION_FILE'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

with open(section_file, 'r', encoding='utf-8') as f:
    new_content = f.read()

# Find section ## <name> and replace until next ## or end
pattern = rf'(## {re.escape(section_name)}\n)(.*?)(?=\n## |\Z)'
replacement = f'## {section_name}\n{new_content}'

new, count = re.subn(pattern, replacement, content, count=1, flags=re.DOTALL)
if count == 0:
    # Section not found — append before Changelog or at end
    if '## Changelog' in content:
        content = content.replace('## Changelog', f'## {section_name}\n{new_content}\n\n## Changelog')
    else:
        content = content.rstrip() + f'\n\n## {section_name}\n{new_content}\n'
    new = content

with open(path, 'w', encoding='utf-8') as f:
    f.write(new)

print(f'Section \"{section_name}\" updated')
"
        ;;

    diff)
        # List contract sections for comparison
        python3 -c "
import re

path = '$CONTRACT_PATH'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

sections = re.findall(r'^## (.+)$', content, re.MULTILINE)
for s in sections:
    if s not in ('Changelog',):
        print(s)
"
        ;;

    *)
        echo "ERROR: Unknown action: $ACTION" >&2
        echo "HINT: Valid actions: status, changelog, section, diff" >&2
        exit 2
        ;;
esac
