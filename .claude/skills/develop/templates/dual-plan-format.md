# Dual Plan Output Format

When both Claude and Qwen produce plans (Phase 2), merge them into a unified report. The orchestrator reads both outputs and produces the merged plan.

**Merge rules:**
1. **Deduplicate tasks:** Same layer + same goal → keep more detailed, tag `[Claude + Qwen]`
2. **Unique tasks:** Only one planner → tag `[Claude]` or `[Qwen]`
3. **Edge cases:** Union of all, deduplicated, tagged by source
4. **Dependencies:** If disagreement, prefer Claude's ordering
5. **Complexity:** If disagreement, note both estimates

```markdown
## Dual Plan: Claude + Qwen

### Plan Sources
- **Claude** (PM Agent): ✅ Completed
- **Qwen** (Qwen Code): ✅ Completed | ⚠️ Failed (Claude-only plan below)

### Tasks

#### 1. <Task Title> [Claude + Qwen]
Both planners identified this task.
**Layer**: Domain / Application / Infrastructure / UI
**Complexity**: Medium
**Description**: ...

#### 2. <Task Title> [Claude]
Proposed by Claude only.
**Layer**: ...
**Complexity**: ...
**Description**: ...

#### 3. <Task Title> [Qwen]
Proposed by Qwen only.
**Layer**: ...
**Complexity**: ...
**Description**: ...

### Dependencies
1 → 2 → 3 (from Claude's ordering)

### Edge Cases
- [Claude + Qwen] Edge case found by both
- [Claude] Edge case from Claude only
- [Qwen] Edge case from Qwen only

### Planner Comparison

| Aspect | Claude | Qwen |
|--------|--------|------|
| Total tasks | N | M |
| Agreed tasks | X | X |
| Unique tasks | Y | Z |
| Edge cases found | A | B |
```
