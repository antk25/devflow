# Tester Agent Template

Universal testing rules for all tester agents. Project-specific testers extend this with framework knowledge.

## Testing Pyramid

```
        /\
       /  \       E2E Tests (10%) - Critical user paths
      /----\
     /      \     Integration Tests (20%) - API, component integration
    /--------\
   /          \   Unit Tests (70%) - Functions, classes, edge cases
 /--------------\
```

## Test Structure (AAA Pattern)

Every test follows Arrange-Act-Assert:
1. **Arrange** - Set up test data and dependencies
2. **Act** - Execute the code under test
3. **Assert** - Verify the expected outcome

## Coverage Checklist

### Happy Path
- Normal operation with valid inputs
- Expected state transitions

### Edge Cases
- Empty inputs (null, undefined, [], "")
- Boundary values (0, -1, MAX_INT)
- Large datasets

### Error Cases
- Invalid inputs
- Network failures
- Unauthorized access
- Timeout scenarios

### Security
- SQL injection attempts
- XSS payloads
- Authorization bypass

## Live E2E Testing

### API Testing with curl
- After implementing API endpoints
- Verify authentication flows
- Test error handling
- Graceful fallback: if server not running, report "E2E skipped"

### UI Testing with Playwright MCP
- After implementing UI components
- Test user flows (login, checkout, etc.)
- Verify visual state changes
- Graceful fallback: if frontend not running, report "E2E skipped"

### Contract Verification (C-DAD)
When feature contract is provided:
- Status codes must match contract exactly
- Response fields must match contract YAML
- Event payloads must match contract schema
- DTO fields must match contract definition

## E2E Test Report Format

```markdown
## E2E Verification Results

### Backend API
- Endpoint: POST /api/resource
- Status: PASS/FAIL (exact status code)
- Response: Valid JSON, expected fields present/missing

### Frontend UI
- Flow: User registration
- Status: PASS/FAIL
- Steps verified: [list]
```
