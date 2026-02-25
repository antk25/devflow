# Dev Orchestrator

AI-powered development orchestration built natively on Claude Code.

## Overview

Dev Orchestrator coordinates specialized AI agents to plan, implement, test, and review software development tasks. It supports multi-repository projects, E2E testing, and fully autonomous development workflows.

## Prerequisites

**Required:**
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) (v2.0+) with API key configured
- Node.js (v20+)
- Python 3.10+
- Git

**Required MCP servers** (project-level, configured automatically by `setup.sh`):
| Server | Purpose | Install method |
|--------|---------|----------------|
| [Serena](https://github.com/oraios/serena) | Symbolic code navigation, persistent memories | `uvx` (requires [uv](https://docs.astral.sh/uv/getting-started/installation/)) |
| qwen-review | Dual code review (Claude + Qwen) | Bundled, `npm install` |

**Optional MCP servers** (user-level, install into `~/.claude.json` via `claude mcp add`):
| Server | Purpose | Install command |
|--------|---------|----------------|
| [context7](https://github.com/upstash/context7) | Up-to-date library documentation | `claude mcp add context7 -- npx -y @upstash/context7-mcp` |
| [playwright](https://github.com/anthropics/mcp-playwright) | E2E browser testing | `claude mcp add playwright -- npx -y @playwright/mcp@latest` |
| [chrome-devtools](https://github.com/nicholasgriffintn/chrome-devtools-mcp) | Browser debugging & performance | `claude mcp add chrome-devtools -- npx -y chrome-devtools-mcp@latest` |
| [local-rag](https://github.com/jcassee/mcp-local-rag) | RAG knowledge base for project docs | `claude mcp add local-rag -- npx -y mcp-local-rag` |

> Without optional servers the orchestrator works fine — features that depend on them are gracefully skipped.

## Quick Start

```bash
git clone <repo-url> claude-orchestrator
cd claude-orchestrator
./scripts/setup.sh    # generates .mcp.json, .claude/settings.json, empty data files
claude                # launch Claude Code
```

You'll see:
```
🎯 Dev Orchestrator

Commands:
• /develop <feature> - Autonomous development (smart routing)
• /fix <bug> - Quick bug fix (no planning)
• /refactor <scope> - Code refactoring
• /investigate <issue> - Deep problem analysis (no changes)
• /review [--pr 123] - Code review (local or PR/MR)
• /plan, /implement - Manual workflow
• /project list|switch|add - Project management
• /help - Full documentation

Ready to build!
```

## Features

- **Autonomous development** - Full pipeline with no confirmations
- **Multi-repository support** - Separate frontend/backend repos
- **E2E testing** - curl for API, Playwright for UI
- **PR/MR review** - Review teammate's code from GitHub/GitLab
- **Problem investigation** - Deep analysis without changes
- **Architecture validation** - Auto-fix pattern violations

## Commands

### Autonomous Development

```bash
/develop Add user authentication with JWT
```

Runs the full pipeline automatically:
```
create branch → plan → implement → validate → fix → E2E test → commit → review → fix → summary
```

**Smart routing:** Detects workflow type from keywords:
- "fix", "bug", "error" → routes to `/fix`
- "refactor", "clean up" → routes to `/refactor`

### Quick Bug Fix

```bash
/fix Login button not responding
/fix TypeError in user profile
```

Streamlined pipeline (no planning):
```
create branch → search → implement → test → commit → summary
```

### Problem Investigation

```bash
/investigate Login fails intermittently
/investigate Why is the API response slow?
/investigate --deep Memory leak in dashboard
```

Deep analysis without changes:
```
search → analyze → hypotheses → solutions report
```

**Output includes:**
- Root cause analysis with evidence
- Hypotheses ranked by confidence
- Solution options with effort/risk estimates

### Code Refactoring

```bash
/refactor src/services/auth.ts
/refactor Payment service
/refactor --extract UserValidator from UserService
```

Structured refactoring:
```
create branch → analyze → refactor (step by step) → validate → test → commit → summary
```

### Code Review

```bash
/review                          # Staged changes
/review --pr 123                 # GitHub PR
/review --mr 45                  # GitLab MR
/review --branch feature/auth    # Branch vs main
/review --pr 123 --comment       # Post comments to PR
/review --focus security         # Security-focused
```

### Manual Workflow

```bash
/plan Add shopping cart functionality
/implement 1
/implement 2
/review
```

### Project Management

```bash
/project list                    # List registered projects
/project switch <name>           # Switch context
/project add <path>              # Register new project
/project info                    # Current project details
```

## Choosing the Right Command

| Situation | Command | Why |
|-----------|---------|-----|
| New feature | `/develop` | Full planning and review |
| Bug fix (clear cause) | `/fix` | Fast, no planning overhead |
| Bug (unclear cause) | `/investigate` | Analysis first, no changes |
| Code improvement | `/refactor` | Preserves behavior, step-by-step |
| Review your changes | `/review` | Before commit |
| Review teammate's PR | `/review --pr 123` | External code review |
| Manual control | `/plan` → `/implement` | Step-by-step |

## Architecture

```
claude-orchestrator/
├── .claude/
│   ├── CLAUDE.md                    # Main context & routing rules
│   ├── settings.json.example        # Permissions & hooks template
│   ├── data/
│   │   ├── projects.json.example    # Project registry template
│   │   ├── sessions.json.example    # Session tracking template
│   │   └── queue.json.example       # Task queue template
│   ├── agents/                      # Agent system prompts
│   │   ├── pm.md                    # Project Manager
│   │   ├── architect.md             # System Architect
│   │   ├── js-developer.md          # JS/TS Developer
│   │   ├── php-developer.md         # PHP Developer
│   │   ├── tester.md                # QA Engineer
│   │   ├── debugger.md              # Debugging Specialist
│   │   ├── tracer.md                # Business Logic Analyst
│   │   ├── reviewer.md              # Code Reviewer (opus)
│   │   └── architecture-guardian.md # Pattern Validator
│   ├── hooks/                       # Claude Code hooks
│   │   ├── auto-approve.sh          # Auto-approve safe tool calls
│   │   ├── project-restore.sh       # Restore project context on start
│   │   └── rag-reindex-check.sh     # Check RAG knowledge base updates
│   └── skills/                      # Slash command definitions
│       ├── develop/SKILL.md         # /develop — autonomous pipeline
│       ├── fix/SKILL.md             # /fix — quick bug fix
│       ├── refactor/SKILL.md        # /refactor — code improvement
│       ├── investigate/SKILL.md     # /investigate — deep analysis
│       ├── explore/SKILL.md         # /explore — research approaches
│       ├── review/SKILL.md          # /review — code review
│       ├── plan/SKILL.md            # /plan — manual planning
│       ├── implement/SKILL.md       # /implement — manual implementation
│       ├── finalize/SKILL.md        # /finalize — clean commit history
│       ├── note/SKILL.md            # /note — Obsidian integration
│       ├── queue/SKILL.md           # /queue — batch task execution
│       ├── project/SKILL.md         # /project — registry management
│       ├── audit/SKILL.md           # /audit — docs vs code check
│       ├── next/SKILL.md            # /next — task transition
│       └── help/SKILL.md            # /help — show commands
├── scripts/                         # Shell utilities
│   ├── setup.sh                     # Initial setup (run after clone)
│   ├── create-branch.sh             # Branch creation with conventions
│   ├── session-checkpoint.sh        # Session phase tracking
│   ├── read-project-config.sh       # Project config reader
│   ├── git-context.sh               # Commit style analyzer
│   ├── run-tests.sh                 # Universal test runner
│   ├── e2e-check.sh                 # E2E test runner
│   ├── check-loop.sh                # Loop detection
│   └── require-contract.sh          # C-DAD contract gate
├── mcp-servers/
│   └── qwen-review/                 # Bundled MCP server for dual review
├── .mcp.json.example                # MCP server config template
├── start.sh                         # Project launcher (interactive menu)
└── README.md
```

## Agents

| Agent | Role | Use Cases |
|-------|------|-----------|
| **PM** | Project Manager | Requirements analysis, task breakdown |
| **Architect** | System Architect | Architecture design, ADRs |
| **JS Developer** | JavaScript/TypeScript | React, Vue, Node.js, Next.js |
| **PHP Developer** | PHP | Laravel, Symfony |
| **Tester** | QA Engineer | Unit, integration, E2E tests |
| **Reviewer** | Code Reviewer | Security, performance, quality |
| **Architecture Guardian** | Pattern Validator | Validates code, requests fixes |

## Project Configuration

Projects support multi-repository setups:

```json
{
  "name": "my-fullstack-app",
  "path": "/home/user/projects/my-app",
  "type": "fullstack",
  "repositories": {
    "backend": "/home/user/projects/my-app/backend",
    "frontend": "/home/user/projects/my-app/frontend"
  },
  "testing": {
    "backend": {
      "type": "api",
      "base_url": "http://localhost:8000",
      "commands": {
        "unit": "cd {{repo}} && ./vendor/bin/phpunit",
        "e2e": "curl -s {{base_url}}/api/health | jq ."
      }
    },
    "frontend": {
      "type": "browser",
      "base_url": "http://localhost:3000",
      "commands": {
        "unit": "cd {{repo}} && npm test",
        "e2e": "cd {{repo}} && npx playwright test"
      }
    }
  }
}
```

## Git Workflow

| Command | Branch Prefix | Commit Prefix | Creates Branch |
|---------|---------------|---------------|----------------|
| `/develop` | `feature/` | `feat:` | Yes |
| `/fix` | `fix/` | `fix:` | Yes |
| `/refactor` | `refactor/` | `refactor:` | Yes |
| `/investigate` | - | - | No (read-only) |
| `/review` | - | - | No (read-only) |

**Safety:** `git push` is always manual - you control when to push.

## Autonomous Mode

The `/develop`, `/fix`, and `/refactor` commands run without confirmations:

- No file edit confirmations
- No command confirmations
- Automatic architecture validation and fix
- Automatic E2E testing and fix
- Automatic code review and fix

**Safety is maintained through:**
- `git push` blocked in settings.json
- All changes stay local until you push
- Full summary provided at the end

## Integration

- **Git** - Auto branches, auto commits
- **GitHub/GitLab** - PR/MR review
- **Playwright** - E2E browser testing
- **Jest/PHPUnit** - Unit testing
- **ESLint/PHPStan** - Static analysis
- **Serena MCP** - Symbolic code navigation

## License

MIT
