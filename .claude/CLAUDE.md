# Dev Orchestrator - Claude Code Native

## Startup Greeting

**IMPORTANT:** When starting a new conversation in this project, ALWAYS greet the user with a brief welcome showing available commands:

```
🎯 **Dev Orchestrator**

Just describe your task — I'll pick the right workflow automatically.
Or use a command directly:

• `/develop` · `/fix` · `/refactor` · `/explore` · `/investigate` · `/review`
• `/plan` · `/implement` · `/finalize` · `/audit` · `/note` · `/queue`
• `/next` · `/project` · `/help`

Ready to build!
```

---

## Project Auto-Restore (SessionStart Hook)

A `SessionStart` hook runs `project-restore.sh` which outputs the active project info. When you see `PROJECT_RESTORE` in hook output:

1. Read the output fields: `name`, `type`, `serena`, `path`
2. If `serena` is not empty, call `mcp__serena__activate_project(project=<serena>)`
3. Include the active project name in your startup greeting: `**Active project:** <name>`

This ensures project context is automatically restored after `/clear`.

---

## Auto-Routing (Smart Task Dispatch)

**IMPORTANT:** When the user sends a task description **without a slash command**, you MUST analyze the intent and invoke the appropriate skill automatically via the `Skill` tool. Do NOT ask the user which command to use — route it yourself.

### How it works

1. User sends a message (not a slash command, not a question about the codebase)
2. You analyze the intent using the routing matrix below
3. You briefly announce the chosen route: `→ /fix` or `→ /develop` (one line, no explanation)
4. You invoke `Skill(skill: "<name>", args: "<user's message>")` immediately

### Routing Matrix

Evaluate the user's message against these categories **in priority order** (first match wins):

| Priority | Route | Intent Signals | Examples |
|----------|-------|----------------|----------|
| 1 | `/fix` | Bug, error, broken behavior, incorrect result, crash, regression, "не работает", "неправильно", "ошибка", "сломал" | "Login returns 500", "Расчёт КВ показывает неправильный процент" |
| 2 | `/investigate` | Need to understand WHY something happens, unclear root cause, performance issue, intermittent problem, "почему", "разобраться", "медленно", "иногда" | "Почему отчёт генерируется 30 секунд?", "Иногда API возвращает пустой ответ" |
| 3 | `/explore` | Vague idea, need to compare approaches, "как лучше", "варианты", "предложи", research before implementation | "Как лучше реализовать уведомления?", "Предложи подход к кешированию" |
| 4 | `/refactor` | Code improvement without behavior change, cleanup, extract, rename, restructure, "рефактор", "вынести", "переименовать", "упростить" | "Вынести валидацию из контроллера в сервис", "Упростить метод calculateBonus" |
| 5 | `/review` | Review code, PR, MR, check quality, "ревью", "проверь код", "посмотри PR" | "Проверь мой последний коммит", "Review PR 123" |
| 6 | `/audit` | Documentation accuracy, patterns drift, "аудит", "документация устарела" | "Проверь что patterns.md соответствует коду" |
| 7 | `/develop` | New feature, add functionality, implement something specific, "добавить", "реализовать", "сделать", "нужно" | "Добавить фильтр по дате в отчёт", "Реализовать экспорт в Excel" |

### Rules

- **Priority order matters**: "Расчёт работает неправильно" → `/fix` (priority 1), NOT `/develop` (priority 7)
- **Ambiguous? Ask.** If the message could be either `/fix` or `/develop`, or either `/investigate` or `/explore`, use `AskUserQuestion` with 2 options describing the difference
- **Questions about code are NOT routed.** If the user asks "How does X work?" or "Show me the code for Y" — just answer directly, don't invoke a skill
- **Data queries are NOT routed.** If the user asks to run SQL, check data, show logs — just do it directly
- **Already using a slash command?** Don't re-route. `/develop fix the bug` should go to `/develop`, not `/fix` — the user explicitly chose

### Confidence signals

High confidence (route immediately):
- Explicit action words: "fix", "add", "refactor", "investigate", "explore"
- Error descriptions with stack traces or error messages
- Clear feature requests with acceptance criteria

Low confidence (ask user):
- Single-word messages: "auth", "performance"
- Messages that mix intents: "Fix the bug and add a new feature"
- Messages about process: "What should we do about X?"

---

## Overview

Dev Orchestrator is an AI-powered development orchestration system built natively on Claude Code. It coordinates specialized agents to plan, implement, test, and review software development tasks.

**Key Features:**
- Multi-repository support (separate frontend/backend repos)
- E2E testing (curl for API, Playwright for UI)
- Fully autonomous mode with no confirmations
- Architecture validation and auto-fix
- Contract-Driven AI Development (C-DAD) with Obsidian integration

## Agents

| Agent | Role | Use Case |
|-------|------|----------|
| **PM** | Project Manager | Requirements analysis, task breakdown, sprint planning |
| **Architect** | System Architect | Architecture design, ADRs, technical decisions |
| **JS Developer** | JavaScript/TypeScript Developer | React, Vue, Node.js, TypeScript implementation |
| **PHP Developer** | PHP Developer | Laravel, Symfony, PHP implementation |
| **Tester** | QA Engineer | Unit, Integration, E2E testing |
| **Debugger** | Debugging Specialist | Root cause analysis, systematic investigation, diagnostics |
| **Tracer** | Business Logic Analyst | Traces data flows, event chains, entity relationships before implementation |
| **Reviewer** | Code Reviewer | Security audit, performance review, code quality (opus) |
| **Architecture Guardian** | Pattern Validator | Validates code against project patterns, requests fixes |

## Agent Selection

When using Task tool to spawn agents, use these identifiers:

- `Project Manager` - Requirements and planning
- `Architect` - Architecture design
- `JS Developer` - JavaScript/TypeScript Developer
- `PHP Developer` - PHP Developer
- `Tester` - QA/Test Engineer
- `Debugger` - Root cause analysis and investigation
- `Code Reviewer` - Code review (runs on opus model)
- `Architecture Guardian` - Pattern validation

## Choosing the Right Command

**Note:** You don't need to memorize this table. Just describe your task and the orchestrator will auto-route to the right command (see [Auto-Routing](#auto-routing-smart-task-dispatch) section).

| Situation | Command | Why |
|-----------|---------|-----|
| New feature | `/develop` | Full planning, review, clean commits |
| Vague feature idea | `/explore` | Research, propose approaches, then decide |
| Bug fix (clear cause) | `/fix` | Fast, no planning overhead |
| Bug (unclear cause) | `/investigate` | Analysis first, no changes |
| Code improvement | `/refactor` | Preserves behavior, step-by-step |
| Review your changes | `/review` | Before commit |
| Review teammate's PR | `/review --pr 123` | External code review |
| Messy git history | `/finalize` | Clean up before PR |
| Batch work | `/queue` | Plan day's work, run as batch |
| Docs out of date | `/audit` | Compare docs with code reality |
| Save dev notes | `/note save` | Persist research/decisions to Obsidian |
| Read TZ from Obsidian | `/note tz` | Load spec and route to workflow |
| Review feature contract | `/note contract <branch>` | Read/approve contract in Obsidian |
| Done with task, starting next | `/next` | Wrap up context, keep project |
| Manual control | `/plan` → `/implement` → `/finalize` | Step-by-step with approval |

## Project Patterns

Each project should define its patterns in `.claude/patterns.md`. The orchestrator reads these when validating code.

If no patterns.md exists, the orchestrator will:
1. Read CLAUDE.md and CONTRIBUTING.md for conventions
2. Analyze existing code for patterns
3. Check git history for commit/branch conventions

See `.claude/patterns.template.md` for the template.

## Conventions

### Code Standards

- **TypeScript**: Strict mode, ESLint, Prettier
- **PHP**: PSR-12, PHPStan level 6
- **Tests**: Required for all new features
- **Documentation**: JSDoc/PHPDoc for public APIs

### Type Change Propagation Rule

When changing a property type (e.g., `string` → `int`), trace the change through ALL layers that touch this property:

1. **Find all callers**: who constructs the class containing the property?
2. **Find all consumers**: who reads this property?
3. **Update each caller/consumer** to match the new type
4. **Check boundary layers** (HTTP controllers, API Platform providers/processors) — they often need explicit casts from string URL params to `int`

**Key insight:** URL parameters are always strings. The `(int)` cast belongs at the HTTP boundary (Provider/Processor), NOT in domain or application layers.

### Git Workflow (Autonomous Mode)

Commands that modify code handle git automatically:

| Command | Work Branch | Final Branch | Commit Style |
|---------|-------------|--------------|--------------|
| `/develop` | `feature/xxx-work` | `feature/xxx` | atomic (from project) |
| `/fix` | - | `fix/xxx` | single commit |
| `/refactor` | - | `refactor/xxx` | per step |
| `/explore` | - | - | No changes |
| `/investigate` | - | - | No changes |
| `/review` | - | - | No changes |
| `/audit` | - | - | docs commit (if --fix) |
| `/note` | - | - | No changes (writes to vault) |
| `/queue` | (per item) | (per item) | delegates to invoked skill |

- Branch naming convention read from project
- Commit message format analyzed from git log
- Never pushes (you control this)

Blocked commands (for safety):
- `git push` - always manual
- `gh` commands - always manual

## Integration

This orchestrator integrates with:
- Git for version control (auto branches, auto commits)
- npm/composer for dependencies
- Jest/PHPUnit for testing
- ESLint/PHPStan for static analysis
- Serena MCP for symbolic code navigation and memories
- Local RAG (mcp-local-rag) for documentation and pattern retrieval

## Extended Documentation

Detailed docs are in `.claude/docs/` — skills read them when needed:

- **`.claude/docs/workflows.md`** — Detailed workflow descriptions, session tracking, project config schema
- **`.claude/docs/infrastructure.md`** — Local RAG, autonomous mode, permissions, troubleshooting
- **`.claude/docs/multi-project.md`** — Multi-project management, launcher script, batch queue
