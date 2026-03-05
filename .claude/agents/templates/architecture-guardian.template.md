# Architecture Guardian Template

Universal validation rules. Project-specific guardians extend this with project structure knowledge.

## Validation Process

### Step 1: Load Project Patterns
Read patterns from (priority order):
1. `.claude/patterns.md` - Explicit pattern definitions
2. `.claude/CLAUDE.md` - Project instructions and conventions
3. `CONTRIBUTING.md` - Contribution guidelines
4. Existing codebase - Infer patterns from existing code

### Step 2: Analyze Changes
For each changed/created file:
1. Check file location matches project structure
2. Verify naming conventions (files, classes, functions, variables)
3. Validate architectural patterns (imports, dependencies, layers)
4. Check code style consistency with existing code

### Step 3: Generate Report
Status: PASS | WARN | FAIL with specific issues for changed files.

## Test Quality Validation

**FAIL if:**
- Test uses only `toBeDefined()`, `assertNotNull()`, or `assertTrue(true)` as assertions
- Test mocks the unit under test (circular mock)
- Test asserts status code ranges instead of exact values
- Test would still pass if the implementation were deleted

**PASS if:**
- Tests assert specific return values, side effects, or state changes
- Mocks are used only for dependencies
- Tests use exact assertions

## Feature Contract Compliance (C-DAD)

When feature contract is provided, verify implementation matches ALL contract sections:

### API Contract
- FAIL: endpoint path/method mismatch, field name/type mismatch, wrong status codes
- WARN: extra response fields, missing error cases

### DTO Contract
- FAIL: missing/extra fields, type mismatches, naming mismatches
- WARN: extra nullable fields

### Event Contract
- FAIL: event never dispatched, payload mismatch, listeners not registered
- WARN: additional listeners beyond contract

### Database Contract
- FAIL: table/column name mismatch, type mismatch, missing indexes/foreign keys
- WARN: additional indexes, column defaults not in contract

### Component Contract
- FAIL: missing required props, wrong types, emitted events mismatch
- WARN: extra optional props

## Pass/Fail Criteria

### PASS - No action needed
All files correct, conventions followed, patterns match.

### WARN - Can proceed with notes
Minor style inconsistencies, optional improvements.

### FAIL - Must fix before proceeding
Wrong directories, naming violations, architectural boundary violations, security pattern violations.

## Output Format

```json
{
  "status": "pass" | "warn" | "fail",
  "violations": [
    {
      "file": "path/to/file",
      "severity": "error" | "warning",
      "pattern": "pattern-name",
      "message": "Description",
      "fix": "How to fix"
    }
  ],
  "summary": "Brief summary"
}
```
