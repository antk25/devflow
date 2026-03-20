# Step 6: Present Results

**Default:** merge debate-resolved findings into the final report.
**If `--no-debate`:** merge preliminary findings with standard confidence scoring.
**If only 1 reviewer:** format that reviewer's output directly.

## Merge Rules (Triple Review)

1. **Deduplicate:** Same file + same problem → keep most detailed, tag all sources (e.g., `[Claude + Qwen + ChatGPT]`)
2. **Unique findings:** Tag with single source: `[Claude]`, `[Qwen]`, or `[ChatGPT]`
3. **Severity:** If reviewers disagree, use the highest severity
4. **Confidence:**
   - 3 reviewers agree → highest confidence, fix first
   - 2 reviewers agree → high confidence
   - 1 reviewer only → normal confidence

## Output Format: Local Reviews

```markdown
## Triple Code Review: Claude + Qwen + ChatGPT

### Review Sources
- **Claude** (Code Reviewer): ✅ Completed | ⚠️ Failed
- **Qwen** (Qwen Code): ✅ Completed | ⚠️ Failed
- **ChatGPT** (Codex CLI): ✅ Completed | ⚠️ Failed

### Summary
**Status**: ✅ Approved | ⚠️ Changes Requested | ❌ Needs Work
**Agreement**: X of Y issues found by 2+ reviewers
**Files Reviewed**: X
**Issues Found**: X critical, X warnings, X suggestions

---

### 🔴 Critical Issues

#### 1. [Issue Title] [Claude + Qwen + ChatGPT]
**File**: `path/to/file.ts:42`
**Category**: Security | Performance | Quality

**Problem**: [Description]
**Fix**: [Recommended fix with code]

---

### 🟡 Warnings
(same format, tagged by source)

### 🔵 Suggestions
(same format, tagged by source)

### ✨ Positive Observations
(merged from all reviewers)

### Reviewer Comparison

| Category | Claude | Qwen | ChatGPT | All 3 | 2 of 3 |
|----------|--------|------|---------|-------|--------|
| Critical | - | - | - | - | - |
| Warnings | - | - | - | - | - |
| Suggestions | - | - | - | - | - |
```

## Output Format: External PR/MR Reviews

```markdown
## 🔍 PR Review: #123 - [Title]

### PR Information
**Author**: @developer-name
**Branch**: `feature/x` → `main`
**Files Changed**: N (+X, -Y)

### Summary
**Verdict**: ✅ Approve | 🔄 Request Changes | 💬 Comment

---

### 🔴 Must Fix Before Merge
(tagged by source)

### 🟡 Should Fix
(tagged by source)

### 💬 Questions for Author

### ✅ Looks Good

### Review Actions
gh pr review 123 --approve
gh pr review 123 --request-changes --body "..."
```

## Output Format: Autonomous Mode (`/develop` calling review)

```json
{
  "status": "pass" | "fail",
  "mode": "triple",
  "critical": [
    {
      "file": "src/auth.ts",
      "line": 42,
      "issue": "SQL injection",
      "fix": "Use parameterized query",
      "source": ["claude", "qwen", "chatgpt"]
    }
  ],
  "warnings": [...],
  "summary": "1 critical (all 3 agree), 2 warnings"
}
```

## Quick Review Mode (`--quick`)

```markdown
## Quick Review: N files

✅ `auth.ts` - No critical issues
⚠️ `user.ts:42` - Missing null check
🔴 `api.ts:15` - SQL injection risk

Run `/review` for detailed analysis.
```
