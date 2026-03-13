# Dual Contract Output Format

When both Claude and Qwen produce contracts (Phase 2.5), merge them into a unified contract. The merged contract uses Claude as the base, enriched with Qwen's additions.

**Merge rules:**
1. **Sections:** Union — if both have same section, merge entries within
2. **Same entries:** Keep Claude's version, annotate Qwen differences as YAML comments
3. **Extra entries:** Tag with `# [Claude]` or `# [Qwen]` YAML comments
4. **Type conflicts:** Note both: `type: string # [Claude: string, Qwen: int] — verify`
5. **Descriptions:** Use Claude's Russian descriptions as primary

**Frontmatter includes sources:**

```markdown
---
created: YYYY-MM-DD
project: <project_name>
type: contract
branch: <branch_name>
status: draft
sources: [claude, qwen]
tags: [контракт, <domain_tags_ru>]
---

# Контракт: <Feature Name>

## Описание

<Claude's description>

---

## API

<Claude's description, enriched with Qwen's observations>

```yaml
api:
  - method: POST
    path: /api/resource
    auth: bearer
    request:
      body:
        field_name: { type: string, required: true }  # [Claude + Qwen]
        extra_field: { type: int }  # [Qwen] — not in Claude's contract, verify if needed
    response:
      201:
        id: { type: int }
        field_name: { type: string }
      400:
        error: { type: string }
        violations: { type: "array<{field: string, message: string}>" }  # [Claude]
```

## DTO

```yaml
dtos:
  CreateResourceCommand:
    field_name: { type: string }  # [Claude + Qwen]
    status: { type: string }  # [Claude: string, Qwen: enum(active,inactive)] — verify
```
```

**Acceptance Scenarios section (always present, after all technical sections):**

```markdown
---

## Acceptance Scenarios

### Scenario: <краткое название>
**Type:** API / UI / API+UI
**Given:** <предусловия — фикстуры, состояние БД, роль пользователя>
**When:** <действие — HTTP-запрос / UI-взаимодействие>
**Then:** <ожидаемый результат — статус, данные, файл, элемент на экране>

### Scenario: <next scenario>
...
```

**Rules for scenarios:**
- Each scenario = one verifiable behavior (split complex flows)
- API: include HTTP method, path, body, expected status + response structure
- UI: describe user actions and visible results, not implementation
- Cover: happy path, permissions (who can/cannot), edge cases
- Write descriptions in Russian, technical details (endpoints, fields) in English

---

**Contract comparison footer (after all sections):**

```markdown
---

## Contract Sources

| Section | Claude | Qwen | Agreed |
|---------|--------|------|--------|
| API endpoints | 2 | 2 | 2 |
| DTOs | 3 | 2 | 2 |
| Events | 1 | 1 | 1 |
| DB tables | 1 | 1 | 0 |
| Acceptance scenarios | 5 | — | — |
| Conflicts to resolve | — | — | 2 |
```
