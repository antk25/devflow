---
name: investigate
description: Deep investigation of bugs and issues without making changes
user_invocable: true
arguments:
  - name: issue
    description: Bug description, error message, or symptom to investigate
    required: true
---

# /investigate - Problem Investigation Skill

This skill performs deep investigation of bugs, errors, and issues **without making any changes**. Returns a detailed analysis with hypotheses and proposed solutions.

## Usage

```
/investigate Login fails intermittently
/investigate TypeError: Cannot read property 'map' of undefined
/investigate Why is the API response slow?
/investigate Memory leak in dashboard component
```

## What It Does

1. **Searches for symptoms** (error messages, keywords)
2. **Analyzes code flow** (traces execution path)
3. **Identifies root causes** (hypotheses with evidence)
4. **Proposes solutions** (ranked by likelihood)
5. **Documents findings** (structured report)

**NO changes made** - pure investigation and analysis.

## Instructions

You are the investigation orchestrator. Perform thorough analysis without modifying any code.

### Phase 1: Understand the Symptom

Parse the issue description to identify:
- Error messages (exact text)
- Affected functionality
- Conditions when it occurs
- Frequency (always, intermittent, specific cases)

After parsing keywords, **query RAG** for architecture context:
```
mcp__local-rag__query_documents(query: "<project_name> <symptom_keywords> architecture flow", limit: 10)
```
- Filter results: only include chunks with score < 0.55 (loose — cast wide net for clues)
- Format as `rag_context` (max ~2000 chars)
- If no relevant results or RAG unavailable, skip silently

### Phase 2: Search for Evidence

```
Task(
  description: "Search: <issue>",
  prompt: "Investigate this issue in the codebase:

## Issue
<issue description>

<if rag_context is not empty, append:>

## Architecture Context (from Knowledge Base)
<rag_context>

Use this to understand system architecture and trace code flow.

## Instructions
1. Search for error messages, keywords, related function names
2. Find all files that could be involved
3. Trace the code flow from entry point to where the issue manifests
4. Look for:
   - Recent changes (git log)
   - Similar patterns elsewhere
   - Related tests (passing or failing)
   - Comments mentioning the issue

Return:
- All relevant files with line numbers
- Code flow diagram (text)
- Observations and anomalies found",
  subagent_type: "Explore",
  model: "sonnet"
)
```

### Phase 3: Deep Analysis

For each candidate location, analyze:

```
Task(
  description: "Analyze: <file/component>",
  prompt: "Analyze this code for the reported issue:

## Issue
<issue description>

## Code Location
<file:lines>

## Context
<surrounding code, related files>

## Instructions
Analyze for:
1. Logic errors
2. Edge cases not handled
3. Race conditions
4. State management issues
5. Type mismatches
6. Null/undefined handling
7. Async/await issues
8. Resource leaks

Return:
- Specific problems found
- Evidence supporting each finding
- Confidence level (high/medium/low)",
  subagent_type: "general-purpose",
  model: "sonnet"
)
```

### Phase 4: Form Hypotheses

Based on analysis, form ranked hypotheses:

```markdown
## Hypothesis 1: [Most Likely]
**Confidence**: High (80%)
**Evidence**:
- [specific code reference]
- [observed behavior]

**Explanation**: [Why this causes the issue]

## Hypothesis 2: [Alternative]
**Confidence**: Medium (50%)
...
```

### Phase 5: Propose Solutions

For each hypothesis, propose solutions:

```markdown
## Solution for Hypothesis 1

### Option A: [Quick Fix]
**Effort**: Low
**Risk**: Low
**Changes**:
- `file.ts:42` - Add null check
- `file.ts:50` - Handle edge case

### Option B: [Proper Fix]
**Effort**: Medium
**Risk**: Low
**Changes**:
- Refactor error handling in `module.ts`
- Add validation layer
```

### Phase 6: Generate Report

Output the complete investigation report:

```markdown
## 🔍 Investigation Report: [Issue]

### Summary
**Status**: Root cause identified | Multiple hypotheses | Needs more data
**Confidence**: High | Medium | Low
**Affected Components**: [list]

---

### Symptom Analysis

**Reported Issue**: [original description]

**Observed Behavior**:
- [what actually happens]

**Expected Behavior**:
- [what should happen]

**Reproduction**:
- [steps if identified]

---

### Code Flow Analysis

```
[Entry Point] → [Component A] → [Service B] → [Problem Location]
     ↓              ↓               ↓              ↓
  user action    validates      calls API      💥 fails here
```

**Key Files**:
| File | Role | Relevance |
|------|------|-----------|
| `src/auth.ts:42` | Authentication | Entry point |
| `src/api/client.ts:100` | API calls | Error originates here |

---

### Root Cause Analysis

#### Hypothesis 1: [Primary] ⭐
**Confidence**: 85%

**Problem**: [description]

**Evidence**:
1. `file.ts:42` - [specific issue]
   ```typescript
   // This code doesn't handle null
   const name = user.profile.name;
   ```
2. Git blame shows change on 2024-01-15
3. Related test is skipped

**Why This Causes the Issue**:
[Explanation of the causal chain]

#### Hypothesis 2: [Alternative]
**Confidence**: 40%
...

---

### Proposed Solutions

#### For Hypothesis 1

**Option A: Quick Fix** ⚡
- Effort: 15 min
- Risk: Low
- Files: 1

```typescript
// Before
const name = user.profile.name;

// After
const name = user?.profile?.name ?? 'Unknown';
```

**Option B: Proper Fix** ✨
- Effort: 1 hour
- Risk: Low
- Files: 3

1. Add null check in `getUser()`
2. Add validation in `UserProfile` component
3. Add test for edge case

---

### Additional Findings

**Related Issues**:
- Similar pattern in `other-file.ts:88`
- TODO comment mentions this: "// FIXME: handle null user"

**Technical Debt**:
- Missing error boundaries
- No input validation

**Recommendations**:
1. Fix primary issue using Option B
2. Add regression test
3. Consider refactoring error handling globally

---

### Next Steps

To fix this issue:
```bash
/fix [specific fix description based on findings]
```

Or for manual investigation:
```bash
# Check the main suspect
cat src/api/client.ts | head -120

# Look at recent changes
git log -p src/api/client.ts --since="2024-01-01"

# Run related tests
npm test -- --grep "auth"
```
```

## Flags

```
/investigate --deep <issue>     # More thorough, checks git history
/investigate --quick <issue>    # Fast scan, top 3 suspects only
/investigate --test <issue>     # Also run tests to gather more data
```

## Integration with Other Commands

After investigation:
```bash
# If root cause is clear
/fix <specific fix based on investigation>

# If architectural changes needed
/develop <feature to address underlying issue>

# If needs discussion
# Share the report with the team
```

## When to Use

✅ **Use /investigate when:**
- Bug is unclear or intermittent
- Need to understand before fixing
- Want to document findings
- Multiple possible causes
- Complex system interactions

❌ **Use /fix instead when:**
- Bug is obvious
- You know what to fix
- Simple typo or config issue
