#!/bin/bash
# obsidian-active.sh — List active Obsidian documents for a project
#
# Usage: obsidian-active.sh [project_name]
#   If project_name is omitted, uses local project.json or active project.
#
# Output: JSON with active contracts, TZ, and improvement-notes.
# Exit codes:
#   0 = success (may return empty lists)
#   1 = vault not configured

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$SCRIPT_DIR")"

PROJECT="${1:-}"

python3 -c "
import json, os, re, sys
from pathlib import Path

project = '${PROJECT}'
vault = ''
project_dir_rel = ''

# Try local project.json first
local_config = os.path.join(os.getcwd(), '.claude', 'data', 'project.json')
if os.path.isfile(local_config):
    with open(local_config) as f:
        cfg = json.load(f)
    if not project:
        project = cfg.get('name', '')
    obsidian = cfg.get('obsidian', {})
    vault = obsidian.get('vault', '')
    project_dir_rel = obsidian.get('project_dir', f'projects/{project}')

# Fallback: central projects.json
if not vault:
    projects_file = '$DEVFLOW_DIR/.claude/data/projects.json'
    if os.path.isfile(projects_file):
        with open(projects_file) as f:
            data = json.load(f)
        if not project:
            project = data.get('active', '')
        vault = data.get('obsidian_vault', '')
        project_dir_rel = f'projects/{project}'

if not project:
    sys.exit(0)

if not vault or not os.path.isdir(vault):
    print(json.dumps({'error': 'vault not accessible', 'vault': vault}))
    sys.exit(1)

project_dir = Path(vault) / project_dir_rel
result = {
    'project': project,
    'vault': vault,
    'contracts': [],
    'tz': [],
    'improvements': [],
}

def read_frontmatter(filepath):
    \"\"\"Extract YAML frontmatter from markdown file.\"\"\"
    try:
        text = filepath.read_text(encoding='utf-8')
        if not text.startswith('---'):
            return {}, text
        parts = text.split('---', 2)
        if len(parts) < 3:
            return {}, text
        fm = {}
        for line in parts[1].strip().split('\n'):
            if ':' in line:
                key, _, val = line.partition(':')
                fm[key.strip()] = val.strip()
        return fm, parts[2].strip()
    except Exception:
        return {}, ''

# Active contracts (status != completed)
contracts_dir = project_dir / 'contracts'
if contracts_dir.is_dir():
    for f in sorted(contracts_dir.glob('*.md'), key=lambda x: x.stat().st_mtime, reverse=True):
        fm, body = read_frontmatter(f)
        status = fm.get('status', 'unknown')
        if status in ('completed',):
            continue
        title_match = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
        title = title_match.group(1) if title_match else f.stem
        result['contracts'].append({
            'file': str(f),
            'name': f.stem,
            'status': status,
            'title': title,
            'branch': fm.get('branch', ''),
        })

# Active TZ (status != done)
tz_dir = project_dir / 'tz'
if tz_dir.is_dir():
    for f in sorted(tz_dir.glob('*.md'), key=lambda x: x.stat().st_mtime, reverse=True)[:5]:
        fm, body = read_frontmatter(f)
        status = fm.get('status', 'unknown')
        if status in ('done', 'completed'):
            continue
        title_match = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
        title = title_match.group(1) if title_match else f.stem
        result['tz'].append({
            'file': str(f),
            'name': f.stem,
            'status': status,
            'title': title,
        })

# Recent improvement notes (status = new)
improvements_dir = project_dir / 'improvement-notes'
if improvements_dir.is_dir():
    for f in sorted(improvements_dir.glob('*.md'), key=lambda x: x.stat().st_mtime, reverse=True)[:3]:
        fm, body = read_frontmatter(f)
        status = fm.get('status', 'new')
        if status in ('resolved',):
            continue
        result['improvements'].append({
            'file': str(f),
            'name': f.stem,
            'status': status,
            'branch': fm.get('branch', ''),
        })

json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
print()
" 2>/dev/null || echo '{"error": "script failed"}'
