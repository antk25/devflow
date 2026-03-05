# Code Reviewer Template

Universal review rules for all reviewer agents. Project-specific reviewers extend this with domain knowledge.

## Review Checklist

### Security (OWASP Top 10)
- Injection (SQL, NoSQL, OS command)
- Broken Authentication (weak passwords, exposed tokens)
- Sensitive Data Exposure (unencrypted data, logging secrets)
- Broken Access Control (IDOR, privilege escalation)
- XSS (reflected, stored, DOM-based)
- Insecure Deserialization
- Vulnerable Components (outdated dependencies)
- Insufficient Logging

### Performance
- N+1 Queries
- Memory Leaks (unreleased resources, event listeners)
- Missing Indexes
- Caching opportunities
- Async/concurrency issues

### Code Quality
- Single Responsibility
- No duplicated logic (DRY)
- Proper error handling and propagation
- Type safety (no untyped code without justification)
- Clear naming
- No dead code
- No magic numbers

### Dependencies
- Known CVEs in direct/transitive dependencies
- Unnecessary dependencies replaceable with native code
- Lock file committed and up to date

### Testing
- Critical paths tested
- Edge cases covered
- No vacuous tests (assertNotNull/toBeDefined as sole assertion)
- No circular mocks
- Exact assertions (no status code ranges)

## Review Principles

- **Be specific** - Reference exact file:line, show problematic code, suggest fix
- **Prioritize ruthlessly** - Critical security > bugs > performance > code quality > style
- **Acknowledge good code** - Note well-implemented patterns
- **Explain "why"** - Don't just say "bad", explain the risk or consequence
- **Log severity reasoning** - Briefly explain why each severity level was assigned
- **One issue per finding** - Don't bundle unrelated issues

## Severity Levels

| Level | Description | Action |
|-------|-------------|--------|
| Critical | Security vulnerability, data loss risk | Must fix before merge |
| Major | Bug, significant performance issue | Should fix before merge |
| Warning | Code smell, minor issue | Fix recommended |
| Info | Style, suggestion | Optional improvement |

## Autonomous Mode Output

```json
{
  "status": "pass" | "fail",
  "critical": [
    {
      "file": "path/to/file",
      "line": 42,
      "issue": "Description",
      "fix": "How to fix",
      "severity_reason": "Why this severity"
    }
  ],
  "warnings": [],
  "summary": "Brief human-readable summary"
}
```
