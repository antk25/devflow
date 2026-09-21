"""Read workflow documents; definitions live in Markdown, execution lives in SQLite."""
import hashlib
import re
from pathlib import Path

import yaml


class WorkflowError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    pass


def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, (str, int)) or key in result:
            raise WorkflowError(f"Duplicate or invalid YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def document(path):
    raw = path.read_text(encoding='utf-8')
    meta, body = {}, raw
    if raw.startswith('---\n'):
        match = re.match(r'\A---\n(.*?)\n---(?:\n|$)', raw, re.S)
        if not match:
            raise WorkflowError(f"Unclosed frontmatter: {path}")
        meta = yaml.load(match[1], Loader=UniqueLoader)
        if meta is None:
            meta = {}
        if not isinstance(meta, dict):
            raise WorkflowError(f"Frontmatter must be a mapping: {path}")
        body = raw[match.end():]
    return {'path': str(path), 'raw': raw, 'meta': meta, 'body': body,
            'revision': digest(raw)}


def context(cwd):
    cwd = Path(cwd).resolve()
    meta = document(cwd / 'AGENTS.md')['meta']
    for key in ('project', 'vault'):
        if not isinstance(meta.get(key), str) or not meta[key].strip():
            raise WorkflowError(f"AGENTS.md needs a non-empty {key}")
    vault = Path(meta['vault']).expanduser()
    if not vault.is_absolute():
        vault = cwd / vault
    vault = vault.resolve()
    if not vault.is_dir():
        raise WorkflowError(f'Vault directory is missing or inaccessible: {vault}; mount or create it first')
    return {'project': meta['project'], 'cwd': cwd, 'vault': vault}


def slug_value(value):
    if not re.fullmatch(r'[a-z0-9]+(?:[.-][a-z0-9]+)*', value.lower()):
        raise WorkflowError('Slug must contain Latin letters, digits, dots or hyphens')
    return value.lower()


def resolve_slug(vault, query):
    query = slug_value(query)
    candidates = set()
    for folder in ('tz', 'research', 'plans', 'changelog'):
        for path in (vault / folder).glob('*.md'):
            stem = path.stem.lower()
            if folder == 'changelog':
                stem = re.sub(r'^\d{4}-\d{2}-\d{2}-', '', stem)
            if stem == query or stem.startswith(query + '-'):
                candidates.add(stem)
    if query in candidates:
        return query
    if len(candidates) > 1:
        raise WorkflowError('Ambiguous task; use a full slug: ' + ', '.join(sorted(candidates)))
    return next(iter(candidates), query)


def artifact(vault, folder, slug):
    matches = [p for p in (vault / folder).glob('*.md') if p.stem.lower() == slug]
    if len(matches) > 1:
        raise WorkflowError(f'Duplicate {folder} artifact for {slug}')
    return document(matches[0]) if matches else None


def headings(body):
    """Ignore fenced examples when looking for actual step sections."""
    lines = body.splitlines(keepends=True)
    offset, fence, found = 0, None, []
    for line in lines:
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
        elif fence is None:
            match = re.match(r'^(#{1,3})\s+(.+?)\s*$', line)
            if match:
                found.append((len(match[1]), match[2], offset))
        offset += len(line)
    return found


def plan_steps(doc):
    meta = doc['meta']
    if 'schema' not in meta:
        raise WorkflowError('Legacy plan: run migrate preview before implementation')
    if type(meta['schema']) is not int or meta['schema'] != 1:
        raise WorkflowError('Unsupported plan schema; expected integer 1')
    if not re.fullmatch(r'[0-9a-f]{64}', str(meta.get('research_revision', ''))):
        raise WorkflowError('Plan needs research_revision from the research artifact')
    steps = meta.get('steps')
    if not isinstance(steps, list) or not steps:
        raise WorkflowError('Plan needs a non-empty steps list')
    by_id, numbers = {}, set()
    sections = {}
    hs = headings(doc['body'])
    in_steps = False
    for i, (level, title, start) in enumerate(hs):
        if level <= 2:
            in_steps = level == 2 and title == 'Steps'
        if in_steps and level == 3 and re.match(r'^[a-z][a-z0-9-]*:', title):
            ident = title.split(':', 1)[0]
            if ident in sections:
                raise WorkflowError(f'Duplicate step heading: {ident}')
            end = hs[i + 1][2] if i + 1 < len(hs) else len(doc['body'])
            sections[ident] = doc['body'][start:end].strip()
    for step in steps:
        if not isinstance(step, dict) or set(step) != {'id', 'n', 'blocked_by'}:
            raise WorkflowError('Each step must contain only id, n, blocked_by; statuses belong in SQLite')
        ident, n, deps = step['id'], step['n'], step['blocked_by']
        if not isinstance(ident, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', ident):
            raise WorkflowError(f'Invalid step ID: {ident!r}')
        if ident in by_id or type(n) is not int or n < 1 or n in numbers:
            raise WorkflowError(f'Duplicate ID or invalid/duplicate step number: {ident}')
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            raise WorkflowError(f'Invalid dependencies for {ident}')
        if ident not in sections:
            raise WorkflowError(f'Missing heading: ### {ident}: <title>')
        # Ordering is presentation only. Contracts and dependency identities define the step.
        revision = digest(sections[ident] + '\n' + '\n'.join(sorted(deps)))
        by_id[ident] = dict(step, revision=revision)
        numbers.add(n)
    if set(sections) != set(by_id):
        raise WorkflowError('Step headings and frontmatter IDs must match')
    visiting, visited = set(), set()
    def visit(ident):
        if ident not in by_id:
            raise WorkflowError(f'Unknown dependency: {ident}')
        if ident in visiting:
            raise WorkflowError(f'Dependency cycle at {ident}')
        if ident in visited:
            return
        visiting.add(ident)
        for dep in by_id[ident]['blocked_by']:
            visit(dep)
        visiting.remove(ident)
        visited.add(ident)
    for ident in by_id:
        visit(ident)
    return sorted(by_id.values(), key=lambda s: s['n'])
