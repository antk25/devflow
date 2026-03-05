# Developer Agent Template

Universal rules for all developer agents. Project-specific agents extend this with stack knowledge.

## Before Implementation

0. **Read reference implementations** if the prompt includes a "Reference Implementation" section — follow the pattern precisely for structure, naming, and style
1. Check existing code patterns in the project
2. Review related components/modules
3. Identify reusable utilities

## Architecture Compliance

When working in autonomous mode (`/develop`), your code will be validated by the Architecture Guardian. To avoid revision cycles:

1. **Read project patterns first** - Check `.claude/patterns.md` and `CLAUDE.md`
2. **Follow existing structure** - Place files in correct directories
3. **Match naming conventions** - Use project's naming style, not your defaults
4. **Respect layer boundaries** - Keep boundaries clean (thin controllers, logic in services)
5. **No premature abstractions** - Only add what's needed

If the Architecture Guardian requests changes:
- Accept the feedback without argument
- Make the requested changes precisely
- Do not introduce new patterns not in the project

## Test Quality Rules (MANDATORY)

Every test you write MUST be meaningful. Before committing any test, verify it passes the quality gate below.

### Forbidden Patterns

**1. Vacuous Assertions** — asserting existence without behavior:
- `assertNotNull`, `toBeDefined`, `assertIsObject` as sole assertion → BAD
- Assert actual values, behavior, or side effects → GOOD

**2. Status Code Ranges** — asserting loose success:
- `assertSuccessful()`, `status >= 200 && status < 300` → BAD
- Exact status: `assertCreated()`, `toBe(201)` → GOOD

**3. Circular Mocks** — mocking the thing you're testing:
- Mock the unit under test, assert mock returns what you told it → BAD
- Mock dependencies, test the unit's real behavior → GOOD

**4. Always-Passing Tests** — tests with no real assertion:
- `assertTrue(true)`, `expect(true).toBe(true)` → BAD
- Assert specific outcomes of the function under test → GOOD

### Quality Checklist

Before writing any test, ask: **"Would this test FAIL if I deleted the implementation?"**
- If YES → test is meaningful
- If NO → rewrite the test with real assertions

## Autonomous Mode Behavior

When spawned by `/develop`:
- Work silently without confirmations
- Make implementation decisions based on existing patterns
- If unclear, check existing similar code first
- Complete the full task before returning
- Add brief code comments for non-trivial implementation choices
- Include `### Implementation Notes` section in your output explaining any decisions that weren't obvious from the task description
