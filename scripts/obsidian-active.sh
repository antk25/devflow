#!/bin/bash
# obsidian-active.sh — List active Obsidian documents for a project
#
# Usage: obsidian-active.sh [project_name]
#   If project_name is omitted, uses the active project.
#
# Output: JSON with active contracts, TZ, and improvement-notes.
# Exit codes:
#   0 = success (may return empty lists)
#   1 = vault not configured

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVFLOW_DIR="$(dirname "$SCRIPT_DIR")"
PROJECTS_FILE="$DEVFLOW_DIR/.claude/data/projects.json"

PROJECT="${1:-}"

python3 -c "
import json, os, re, sys
from pathlib import Path

with open('$PROJECTS_FILE') as f:
    data = json.load(f)

project = '${PROJECT}' or data.get('active', '')
if not project:
    sys.exit(0)

vault = data.get('obsidian_vault', '')
if not vault or not os.path.isdir(vault):
    print(json.dumps({'error': 'vault not accessible', 'vault': vault}))
    sys.exit(1)

project_dir = Path(vault) / 'projects' / project
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
        # Extract first heading as title
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
