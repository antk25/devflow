#!/bin/bash
# obsidian-active.sh — List active Obsidian documents for the current project.
#
# Reads vault path from <cwd>/AGENTS.md frontmatter.
# Looks at tz/, research/, plans/ inside the vault and returns items where
# `status` in frontmatter is set and not equal to "done"/"completed"/"archived".
#
# Output: JSON. Empty lists if nothing active.
# Exit codes: 0 always (silent on missing AGENTS.md or vault).

set -euo pipefail

AGENTS_FILE="$(pwd)/AGENTS.md"

if [ ! -f "$AGENTS_FILE" ]; then
    exit 0
fi

python3 - "$AGENTS_FILE" <<'PY' 2>/dev/null || true
import json, re, sys
from pathlib import Path

agents_file = Path(sys.argv[1])
text = agents_file.read_text(encoding='utf-8')

if not text.startswith('---'):
    sys.exit(0)

parts = text.split('---', 2)
if len(parts) < 3:
    sys.exit(0)

fm = {}
for line in parts[1].strip().splitlines():
    if ':' in line:
        k, _, v = line.partition(':')
        fm[k.strip()] = v.strip()

project = fm.get('project', '')
vault = fm.get('vault', '')

if not project or not vault or not Path(vault).is_dir():
    sys.exit(0)

def read_frontmatter(filepath):
    try:
        text = filepath.read_text(encoding='utf-8')
    except Exception:
        return {}, ''
    if not text.startswith('---'):
        return {}, text
    parts = text.split('---', 2)
    if len(parts) < 3:
        return {}, text
    fm = {}
    for line in parts[1].strip().splitlines():
        if ':' in line:
            k, _, v = line.partition(':')
            fm[k.strip()] = v.strip()
    return fm, parts[2].strip()

INACTIVE = {'done', 'completed', 'archived', 'closed'}

def collect(folder, limit=5):
    out = []
    d = Path(vault) / folder
    if not d.is_dir():
        return out
    files = sorted(d.glob('*.md'), key=lambda x: x.stat().st_mtime, reverse=True)
    for f in files[:limit]:
        meta, body = read_frontmatter(f)
        status = (meta.get('status') or '').lower()
        if status in INACTIVE:
            continue
        title_match = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
        title = title_match.group(1) if title_match else f.stem
        out.append({
            'file': str(f),
            'name': f.stem,
            'status': meta.get('status') or 'unknown',
            'title': title,
        })
    return out

result = {
    'project': project,
    'vault': vault,
    'tz': collect('tz'),
    'research': collect('research'),
    'plans': collect('plans'),
}

json.dump(result, sys.stdout, indent=2, ensure_ascii=False)
print()
PY
