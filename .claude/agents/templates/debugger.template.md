# Debugger Agent Template

Template for generating project-specific debug agents. Project agents extend the base `debugger.md` with stack-specific tools and commands.

## How Project Debug Agents Work

The base debugger agent (`debugger.md`) defines abstract debug operations. The project debug agent maps these to concrete MCP tools available in the project.

**Generated file:** `<project>/.claude/agents/debugger.md`
**Used by:** `/fix` and `/investigate` skills, which pass the project debug agent content as `## Debug Tools` section in the Debugger agent's task prompt.

## Required Sections

Every project debug agent MUST include these sections:

### 1. Debug Tool Mapping

Map abstract operations to concrete MCP tools. The debugger uses these mappings to call the right tools.

```markdown
## Debug Tools

### Tool Prefix
`mcp__<server_name>__`

### Operations
| Operation | Tool Call | Notes |
|-----------|----------|-------|
| run_and_catch | `mcp__<server>__run_and_catch` | |
| inspect_at | `mcp__<server>__inspect_at` | |
| eval | `mcp__<server>__eval` | |
| step | `mcp__<server>__step` | |
| get_variable | `mcp__<server>__get_variable` | |
```

If a tool doesn't have a direct 1:1 mapping, describe the equivalent workflow:
```markdown
| run_and_catch | `Bash(npm test)` then `mcp__chrome_devtools__get_console_message` | Two-step |
```

### 2. Test Commands

How to run tests in this project. The debugger needs this to reproduce issues.

```markdown
## Test Commands
- All: `<command>`
- Single: `<command with filter>`
- Suite: `<command with suite>`
```

### 3. Framework-Specific Debugging (optional)

Eval recipes for common debugging scenarios in the project's framework.

```markdown
## Framework Debugging Recipes
- Check service: `eval("$container->get('service_id')")`
- Check state: `eval("$entity->getStatus()")`
```

## Stack Examples

### PHP / Symfony (via php-debug-mcp)

```markdown
## Debug Tools (PHP/Xdebug via php-debug-mcp)

### Tool Prefix
`mcp__php_debug__`

### Operations
| Operation | Tool Call | Notes |
|-----------|----------|-------|
| run_and_catch | `mcp__php_debug__run_and_catch` | Runs PHP command, catches first exception |
| inspect_at | `mcp__php_debug__inspect_at` | Sets breakpoint, returns locals + stack |
| eval | `mcp__php_debug__eval` | Evaluates PHP expression in current scope |
| step | `mcp__php_debug__step` | Step over/into/out |
| get_variable | `mcp__php_debug__get_variable` | Deep-inspect variable by name |

## Test Commands
- All: `php vendor/bin/phpunit`
- Single: `php vendor/bin/phpunit --filter=testMethodName tests/Path/TestFile.php`
- Suite: `php vendor/bin/phpunit --testsuite=Domain`

## Framework Debugging Recipes
- DI container: `eval("$this->container->get('App\\Service\\MyService')")`
- Doctrine UoW: `eval("$this->entityManager->getUnitOfWork()->getScheduledEntityInsertions()")`
- Env check: `eval("$_SERVER['APP_ENV']")`
- Request params: `eval("$request->request->all()")`
```

### JavaScript / Browser (via chrome-devtools MCP)

```markdown
## Debug Tools (Browser via chrome-devtools)

### Tool Prefix
`mcp__chrome_devtools__`

### Operations
| Operation | Tool Call | Notes |
|-----------|----------|-------|
| run_and_catch | `Bash(npm test)` + `mcp__chrome_devtools__list_console_messages` | Run tests, check console |
| inspect_at | `mcp__chrome_devtools__take_snapshot` | DOM + JS state snapshot |
| eval | `mcp__chrome_devtools__evaluate_script` | Evaluate JS in page context |
| step | N/A | Use eval + snapshot instead |
| get_variable | `mcp__chrome_devtools__evaluate_script` | `JSON.stringify(variable)` |

## Test Commands
- All: `npm test`
- Single: `npx jest --testPathPattern=path/to/test.test.ts`
- E2E: `npx playwright test path/to/test.spec.ts`

## Framework Debugging Recipes
- React state: `eval("document.querySelector('[data-testid=app]').__reactFiber$")`
- Redux store: `eval("window.__REDUX_DEVTOOLS_EXTENSION__ && store.getState()")`
- Network: `mcp__chrome_devtools__list_network_requests` to inspect API calls
- Console errors: `mcp__chrome_devtools__list_console_messages` filtered by level
```

### Node.js / Backend (via future node-debug-mcp)

```markdown
## Debug Tools (Node.js via node-debug-mcp)

### Tool Prefix
`mcp__node_debug__`

### Operations
| Operation | Tool Call | Notes |
|-----------|----------|-------|
| run_and_catch | `mcp__node_debug__run_and_catch` | Run Node command, catch exceptions |
| inspect_at | `mcp__node_debug__inspect_at` | Breakpoint + locals |
| eval | `mcp__node_debug__eval` | Evaluate in current scope |
| step | `mcp__node_debug__step` | Step through execution |
| get_variable | `mcp__node_debug__get_variable` | Deep-inspect variable |

## Test Commands
- All: `npm test`
- Single: `npx jest --testPathPattern=test/file.test.ts`
- Integration: `npm run test:integration`
```

### No Debug Tools Available

If a project has no debug MCP configured, the project debug agent should NOT be created. The base debugger will skip Phase 2.5 and use static analysis only — this is the default and works well for most cases.

## Generation via `/project agents`

When `/project agents` generates agents for a project:

1. Check if project has debug MCP servers in `.mcp.json`
2. Detect stack from project config (PHP, JS, Python, etc.)
3. Generate `debugger.md` using the appropriate stack example above
4. Customize test commands based on actual project setup (package.json scripts, composer.json scripts, etc.)
