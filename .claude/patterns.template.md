# Project Patterns Template

Copy this file to `.claude/patterns.md` in your project and customize for your specific conventions.

---

## Git Conventions

### Branch Naming
```
# Pattern: <type>/<description>
# Examples:
feature/user-authentication
fix/login-redirect-bug
refactor/payment-service
```

### Commit Messages
```
# Pattern: <type>(<scope>): <description>
# Examples:
feat(auth): add JWT token validation
fix(ui): correct button alignment on mobile
refactor(api): extract validation logic to service
test(auth): add login flow integration tests
docs(readme): update installation instructions

# Types: feat, fix, refactor, test, docs, chore, style, perf
```

---

## Directory Structure

```
src/
├── components/       # UI components (PascalCase)
├── hooks/           # Custom React hooks (useXxx)
├── services/        # Business logic and API calls
├── utils/           # Pure utility functions
├── types/           # TypeScript type definitions
├── constants/       # Application constants
└── styles/          # Global styles
```

---

## Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Components | PascalCase | `UserProfile.tsx` |
| Hooks | camelCase, use-prefix | `useAuth.ts` |
| Services | camelCase | `authService.ts` |
| Utils | camelCase | `formatDate.ts` |
| Types/Interfaces | PascalCase | `User.ts` |
| Constants | SCREAMING_SNAKE_CASE | `API_BASE_URL` |
| CSS Modules | camelCase | `styles.module.css` |

---

## Code Patterns

### Component Structure
```typescript
// 1. Imports (external → internal → relative → types → styles)
// 2. Types/Interfaces
// 3. Component function
// 4. Hooks at the top
// 5. Handlers
// 6. Return JSX
```

### Error Handling
```typescript
// Use try-catch for async operations
// Propagate errors to error boundaries
// Log errors with context
```

### State Management
```
// Describe your state management approach
// e.g., React Context, Redux, Zustand
```

---

## Forbidden Patterns

- No `any` types in TypeScript
- No inline styles (use CSS modules or styled-components)
- No direct DOM manipulation in React components
- No business logic in components (extract to services/hooks)
- No hardcoded strings (use constants or i18n)

---

## Required Patterns

- All async functions must have error handling
- All components must have TypeScript props interface
- All API calls must go through service layer
- All forms must have validation

---

## Reference Implementations

Place canonical examples of your most common patterns here. Developer agents will use these as the **exact template** to follow when creating new code of the same type.

**Tip:** Only include 2-4 golden samples for your most common patterns. These should be real, working code from your project (not hypothetical examples).

### Service (example)
```
# Paste your canonical service implementation here
# e.g., the best example of a service class in your project
# File: src/services/ExampleService.ts (or app/Services/ExampleService.php)
```

### Controller (example)
```
# Paste your canonical controller implementation here
# e.g., a well-structured controller that follows all project conventions
# File: src/controllers/ExampleController.ts (or app/Http/Controllers/ExampleController.php)
```

### Test (example)
```
# Paste your canonical test file here
# e.g., a test that demonstrates proper setup, assertions, and cleanup
# File: tests/ExampleService.test.ts (or tests/Feature/ExampleTest.php)
```

### Event Handler (example)
```
# Paste your canonical event handler here (if your project uses events)
# File: src/handlers/ExampleHandler.ts (or app/Listeners/ExampleListener.php)
```
