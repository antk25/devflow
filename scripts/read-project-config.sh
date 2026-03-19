#!/bin/bash
# read-project-config.sh — Reads project configuration and outputs structured JSON
#
# Usage: ./scripts/read-project-config.sh [project_path]
#   If project_path is omitted, tries to read from current directory.
#
# Reads from: <project>/.claude/data/project.json (local, per-project config)
# Fallback:   devflow/.claude/data/projects.json (central registry, legacy)
#
# Output: JSON object to stdout with all project config needed for workflows
# Exit codes:
#   0 = success
#   1 = config not found
#   2 = project not found in registry

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$SCRIPT_DIR")"

# Determine project path
PROJECT_PATH="${1:-$(pwd)}"

# Try local project.json first (new per-project config)
LOCAL_CONFIG="$PROJECT_PATH/.claude/data/project.json"

if [ -f "$LOCAL_CONFIG" ]; then
    python3 -c "
import json, os, sys

with open('$LOCAL_CONFIG') as f:
    project = json.load(f)

project_path = '$PROJECT_PATH'

# Build output with all config an agent needs
agent_config_defaults = {
    'recursive_agents': False,
    'max_depth': 3,
    'review_debate': True,
}
agent_config = {**agent_config_defaults, **project.get('agent_config', {})}

# Git config
git_config = project.get('git', {})
if not git_config:
    git_config = {
        'base_branch': 'main',
        'branch': {'prefix': '', 'work_suffix': '-work', 'type_prefix': True},
        'commit': {'format': '{type}: {message}', 'body': True, 'coauthor': True, 'language': 'en'},
        'mr': False,
        'release': False,
    }

# Obsidian config
obsidian = project.get('obsidian', {})
obsidian_vault = obsidian.get('vault', '')
obsidian_project_dir = obsidian.get('project_dir', f'projects/{project.get(\"name\", \"\")}')

output = {
    'name': project.get('name', os.path.basename(project_path)),
    'path': project_path,
    'type': project.get('type', 'single'),
    'description': project.get('description', ''),
    'git': git_config,
    'repositories': project.get('repositories', {}),
    'testing': project.get('testing', {}),
    'docker': project.get('docker', {}),
    'tags': project.get('tags', []),
    'obsidian_vault': obsidian_vault,
    'obsidian_project_dir': obsidian_project_dir,
    'agent_config': agent_config,
}

# Check for project-level files that exist
files_check = {
    'has_claude_md': os.path.isfile(os.path.join(project_path, '.claude', 'CLAUDE.md')),
    'has_patterns_md': os.path.isfile(os.path.join(project_path, '.claude', 'patterns.md')),
    'has_contributing': os.path.isfile(os.path.join(project_path, 'CONTRIBUTING.md')),
    'has_lessons_learned': os.path.isfile(os.path.join(project_path, '.claude', 'data', 'lessons-learned.md')),
    'has_project_agents': os.path.isdir(os.path.join(project_path, '.claude', 'agents')),
}
output['files'] = files_check

json.dump(output, sys.stdout, indent=2, ensure_ascii=False)
print()
"
    exit 0
fi

# Fallback: read from central projects.json (legacy)
PROJECTS_FILE="$DEVFLOW_DIR/.claude/data/projects.json"

if [ ! -f "$PROJECTS_FILE" ]; then
    echo "ERROR: No project.json found at $LOCAL_CONFIG and no central projects.json" >&2
    echo "HINT: Run: devflow-setup.sh project <name>" >&2
    exit 1
fi

# Try to find project by path in central registry
python3 -c "
import json, sys, os

with open('$PROJECTS_FILE') as f:
    data = json.load(f)

project_path = os.path.realpath('$PROJECT_PATH')

# Find project by path
project_name = None
project = None
for name, p in data.get('projects', {}).items():
    if os.path.realpath(p.get('path', '')) == project_path:
        project_name = name
        project = p
        break

# Fallback: try active project
if not project:
    project_name = data.get('active', '')
    project = data.get('projects', {}).get(project_name)

if not project:
    print('ERROR: Project not found in registry', file=sys.stderr)
    sys.exit(2)

agent_config_defaults = {
    'recursive_agents': False,
    'max_depth': 3,
    'review_debate': True,
}
agent_config = {**agent_config_defaults, **project.get('agent_config', {})}

git_config = project.get('git', {})
if not git_config:
    git_config = {
        'base_branch': 'main',
        'branch': {'prefix': '', 'work_suffix': '-work', 'type_prefix': True},
        'commit': {'format': '{type}: {message}', 'body': True, 'coauthor': True, 'language': 'en'},
        'mr': False,
        'release': False,
    }

obsidian_vault = data.get('obsidian_vault', '')

output = {
    'name': project_name,
    'path': project.get('path', ''),
    'type': project.get('type', 'single'),
    'description': project.get('description', ''),
    'git': git_config,
    'repositories': project.get('repositories', {}),
    'testing': project.get('testing', {}),
    'docker': project.get('docker', {}),
    'tags': project.get('tags', []),
    'obsidian_vault': obsidian_vault,
    'obsidian_project_dir': f'projects/{project_name}',
    'agent_config': agent_config,
}

files_check = {
    'has_claude_md': os.path.isfile(os.path.join(project.get('path', ''), '.claude', 'CLAUDE.md')),
    'has_patterns_md': os.path.isfile(os.path.join(project.get('path', ''), '.claude', 'patterns.md')),
    'has_contributing': os.path.isfile(os.path.join(project.get('path', ''), 'CONTRIBUTING.md')),
    'has_lessons_learned': os.path.isfile(os.path.join(project.get('path', ''), '.claude', 'data', 'lessons-learned.md')),
    'has_project_agents': os.path.isdir(os.path.join(project.get('path', ''), '.claude', 'agents')),
}
output['files'] = files_check

json.dump(output, sys.stdout, indent=2, ensure_ascii=False)
print()
"
