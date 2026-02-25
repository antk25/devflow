#!/bin/bash
# read-project-config.sh — Reads project configuration and outputs structured JSON
#
# Usage: ./scripts/read-project-config.sh [project_name]
#   If project_name is omitted, uses the active project from projects.json
#
# Output: JSON object to stdout with all project config needed for workflows
# Exit codes:
#   0 = success
#   1 = projects.json not found or invalid
#   2 = project not found in registry

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR_DIR="$(dirname "$SCRIPT_DIR")"
PROJECTS_FILE="$ORCHESTRATOR_DIR/.claude/data/projects.json"

if [ ! -f "$PROJECTS_FILE" ]; then
    echo "ERROR: projects.json not found at $PROJECTS_FILE" >&2
    echo "HINT: Register a project first with /project add <path>" >&2
    exit 1
fi

PROJECT_NAME="${1:-}"

python3 -c "
import json, sys, os

with open('$PROJECTS_FILE') as f:
    data = json.load(f)

project_name = '${PROJECT_NAME}' or data.get('active', '')
if not project_name:
    print('ERROR: No active project and no project name provided', file=sys.stderr)
    print('HINT: Switch to a project with /project switch <name>', file=sys.stderr)
    print('HINT: Or pass project name: ./scripts/read-project-config.sh <name>', file=sys.stderr)
    sys.exit(1)

project = data.get('projects', {}).get(project_name)
if not project:
    available = ', '.join(data.get('projects', {}).keys())
    print(f'ERROR: Project \"{project_name}\" not found in registry', file=sys.stderr)
    print(f'HINT: Available projects: {available}', file=sys.stderr)
    print(f'HINT: Register with /project add <path>', file=sys.stderr)
    sys.exit(2)

# Build output with all config an agent needs
output = {
    'name': project_name,
    'path': project.get('path', ''),
    'type': project.get('type', 'single'),
    'description': project.get('description', ''),
    'serena_project': project.get('serena_project'),
    'branch_prefix': project.get('branch_prefix', ''),
    'commit_style': project.get('commit_style', {}),
    'repositories': project.get('repositories', {}),
    'testing': project.get('testing', {}),
    'docker': project.get('docker', {}),
    'tags': project.get('tags', []),
    'obsidian_vault': data.get('obsidian_vault', ''),
}

# Check for project-level files that exist
project_path = project.get('path', '')
files_check = {
    'has_claude_md': os.path.isfile(os.path.join(project_path, '.claude', 'CLAUDE.md')),
    'has_patterns_md': os.path.isfile(os.path.join(project_path, '.claude', 'patterns.md')),
    'has_contributing': os.path.isfile(os.path.join(project_path, 'CONTRIBUTING.md')),
    'has_lessons_learned': os.path.isfile(os.path.join(project_path, '.claude', 'data', 'lessons-learned.md')),
}
output['files'] = files_check

json.dump(output, sys.stdout, indent=2, ensure_ascii=False)
print()  # trailing newline
"
