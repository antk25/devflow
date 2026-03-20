---
name: review
description: Review code changes for security, performance, and quality
user_invocable: true
arguments:
  - name: scope
    description: "Files, PR number (--pr 123), branch (--branch name), MR (--mr 45), or 'staged'"
    required: false
    default: staged
---

# /review - Code Review Skill

> **You MUST NOT review the code yourself.** Your role is orchestrator — gather context, spawn reviewers, merge results. If you catch yourself writing review findings directly, STOP and spawn the reviewers instead.

## Usage

```
/review                          # Review git staged changes
/review src/components/          # Review specific directory
/review path/to/file.ts          # Review specific file
/review --pr 123                 # Review GitHub PR #123
/review --mr 45                  # Review GitLab MR #45
/review --branch feature/auth    # Review branch vs main
/review --branch feature/auth --base develop  # Custom base branch

# Options
/review --focus security         # Focus on security issues only
/review --quick                  # Fast review, critical issues only
/review --no-qwen                # Skip Qwen reviewer
/review --no-chatgpt             # Skip ChatGPT reviewer
/review --no-debate              # Skip debate protocol
/review --comment                # Post review comments to PR/MR
```

## Workflow

Execute phases sequentially. **Read the phase file BEFORE executing each step.**

```
Read file: phases/step-N-name.md
```

| Step | File | When |
|------|------|------|
| 1-2 | `phases/step-1-scope.md` | Always |
| 3 | `phases/step-2-patterns.md` | Always (parallel: RAG + analogous code) |
| 4 | `phases/step-3-reviewers.md` | Always — **spawn 3 reviewers in ONE message** |
| 5 | `phases/step-4-debate.md` | Default ON, skip with `--no-debate` |
| 6 | `phases/step-5-present.md` | Always |

**CRITICAL:** Read the phase file BEFORE executing each step. Do NOT rely on memory — the phase file contains exact instructions, prompts, and formats.

## Review Categories

- **Security**: OWASP Top 10, input validation, auth issues, data exposure, injection
- **Performance**: N+1 queries, memory leaks, unnecessary re-renders, missing indexes
- **Code Quality**: SOLID principles, error handling, type safety, duplication, naming

## Posting Comments (--comment flag)

When `--comment` is specified, post review to PR/MR after presenting results:
```bash
gh pr review 123 --comment --body "<review markdown>"
```

## Autonomous Mode

When called by `/develop`, return JSON (see step-5-present.md for format). Critical issues trigger automatic fix loop.
