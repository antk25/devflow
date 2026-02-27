<!-- Keep under 100 lines. Show examples, not rules. -->
# Project Patterns

Copy this file to `.claude/patterns.md` in your project and customize.

## Git Conventions

```
# Branches: <type>/<description>
feature/user-authentication
fix/login-redirect-bug
refactor/payment-service

# Commits: <type>(<scope>): <description>
feat(auth): add JWT token validation
fix(ui): correct button alignment on mobile
refactor(api): extract validation logic to service
# Types: feat, fix, refactor, test, docs, chore, style, perf
```

## Directory Structure

```
src/
├── components/       # UI components (PascalCase: UserProfile.tsx)
├── hooks/            # Custom React hooks (camelCase: useAuth.ts)
├── services/         # Business logic and API calls (camelCase: authService.ts)
├── utils/            # Pure utility functions (camelCase: formatDate.ts)
├── types/            # TypeScript type definitions (PascalCase: User.ts)
├── constants/        # Application constants (SCREAMING_SNAKE_CASE)
└── styles/           # Global styles (camelCase: styles.module.css)
```

## Reference Implementations

Place 2-4 canonical examples of your most common patterns here.
Developer agents will use these as the **exact template** to follow.

**Tip:** Use real, working code from your project — not hypothetical examples.

### Service (example)
```
# Paste your canonical service implementation here
# File: src/services/ExampleService.ts (or app/Services/ExampleService.php)
#
# Code pattern notes (imports → types → class → methods):
#   1. Imports: external → internal → relative → types → styles
#   2. Error handling: try-catch for async, propagate to error boundaries
#   3. State management: describe your approach (Context, Redux, Zustand, etc.)
```

### Controller (example)
```
# Paste your canonical controller implementation here
# File: src/controllers/ExampleController.ts (or app/Http/Controllers/ExampleController.php)
```

### Test (example)
```
# Paste your canonical test file here
# File: tests/ExampleService.test.ts (or tests/Feature/ExampleTest.php)
```

### Event Handler (example)
```
# Paste your canonical event handler here (if your project uses events)
# File: src/handlers/ExampleHandler.ts (or app/Listeners/ExampleListener.php)
```
