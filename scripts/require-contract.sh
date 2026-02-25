#!/bin/bash
# require-contract.sh — Contract phase gate for /develop workflow
#
# Called BEFORE Phase 3 (Implement). Blocks transition if contract is required but missing.
#
# Usage: ./scripts/require-contract.sh <branch> <plan_tasks_json>
#   branch          — session key (work branch name, e.g., "DEV-510-work")
#   plan_tasks_json — JSON string with task summaries from Phase 2 (PM output)
#
# The script checks:
#   1. Was phase_2.5_contract already completed? → SKIP (already done)
#   2. Does the plan meet contract criteria? → REQUIRED or SKIP
#
# Contract criteria (ANY = REQUIRED):
#   - Multi-repo project (frontend + backend)
#   - 2+ tasks touching different layers (API + DB, Handler + Event, etc.)
#   - New domain events or event handler changes
#   - Database schema changes (migrations, new tables/columns)
#
# Exit codes:
#   0 = CONTRACT_SKIP — contract not needed, proceed to Phase 3
#   1 = ERROR — invalid arguments or session not found
#   3 = CONTRACT_REQUIRED — must generate contract before Phase 3
#
# Output: JSON with decision and reasoning

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORCHESTRATOR_DIR="$(dirname "$SCRIPT_DIR")"
SESSIONS_FILE="$ORCHESTRATOR_DIR/.claude/data/sessions.json"
PROJECTS_FILE="$ORCHESTRATOR_DIR/.claude/data/projects.json"

BRANCH="${1:-}"
PLAN_TASKS="${2:-}"

if [ -z "$BRANCH" ]; then
    echo '{"decision":"ERROR","reason":"Branch argument is required"}' >&2
    exit 1
fi

if [ ! -f "$SESSIONS_FILE" ]; then
    echo '{"decision":"ERROR","reason":"sessions.json not found"}' >&2
    exit 1
fi

python3 -c "
import json, sys, os

sessions_file = '$SESSIONS_FILE'
projects_file = '$PROJECTS_FILE'
branch = '$BRANCH'
plan_tasks = '''$PLAN_TASKS'''

# Load session
with open(sessions_file) as f:
    data = json.load(f)

sessions = data.get('sessions', {})
if branch not in sessions:
    print(json.dumps({'decision': 'ERROR', 'reason': f'Session \"{branch}\" not found'}))
    sys.exit(1)

session = sessions[branch]
completed = session.get('completed_phases', [])

# Check 1: Already completed?
if 'phase_2.5_contract' in completed:
    print(json.dumps({'decision': 'SKIP', 'reason': 'Contract phase already completed'}))
    sys.exit(0)

# Check 2: Load project info
project_name = session.get('project', '')
with open(projects_file) as f:
    proj_data = json.load(f)

project = proj_data.get('projects', {}).get(project_name, {})
repos = project.get('repositories', {})
is_multi_repo = len(repos) > 1

# Check 3: Analyze plan for contract criteria
plan_lower = plan_tasks.lower()

# Layer detection keywords
layer_keywords = {
    'api': ['endpoint', 'controller', 'provider', 'resource', 'api ', 'route', 'uri'],
    'database': ['migration', 'entity', 'table', 'column', 'index', 'schema', 'database'],
    'domain': ['handler', 'usecase', 'use case', 'command', 'query', 'service', 'domain'],
    'event': ['event', 'listener', 'subscriber', 'dispatch', 'message'],
    'frontend': ['component', 'page', 'view', 'form', 'button', 'ui', 'frontend', 'react'],
}

touched_layers = set()
for layer, keywords in layer_keywords.items():
    for kw in keywords:
        if kw in plan_lower:
            touched_layers.add(layer)
            break

multi_layer = len(touched_layers) >= 2
has_events = 'event' in touched_layers
has_db_changes = 'database' in touched_layers

# Multi-repo means plan actually touches BOTH frontend and backend layers
backend_layers = touched_layers & {'api', 'database', 'domain', 'event'}
frontend_layers = touched_layers & {'frontend'}
touches_both_repos = is_multi_repo and bool(backend_layers) and bool(frontend_layers)

# Decision
reasons = []
if touches_both_repos:
    reasons.append('multi-repo: touches both frontend and backend')
if multi_layer:
    layers_str = ', '.join(sorted(touched_layers))
    reasons.append(f'touches {len(touched_layers)} layers: {layers_str}')
if has_events:
    reasons.append('involves domain events')
if has_db_changes:
    reasons.append('includes database schema changes')

if reasons:
    result = {
        'decision': 'CONTRACT_REQUIRED',
        'reasons': reasons,
        'touched_layers': sorted(touched_layers),
        'is_multi_repo': is_multi_repo,
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(3)
else:
    result = {
        'decision': 'CONTRACT_SKIP',
        'reason': 'Simple task: single layer, single repo, no events, no schema changes',
        'touched_layers': sorted(touched_layers),
        'is_multi_repo': is_multi_repo,
    }
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0)
"
