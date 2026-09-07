---
name: tokens
description: Token spend statistics across all Claude Code work — by task, project, phase, model, or day, with dollar cost. Reads the local transcripts; nothing is sent anywhere. Also tags the current session to a task so future attribution is exact.
user_invocable: true
arguments:
  - name: args
    description: "Passed through to token-stats.py, e.g. `--by phase --since 2026-07-01`, `--task SE-2032`, `--html ~/tokens.html`, `tag SE-2044`"
    required: false
---

# /tokens — расход токенов по задачам

Single script, no dependencies beyond python3:

```bash
python3 ~/.claude/skills/tokens/token-stats.py [flags]
```

It parses `~/.claude/projects/*/*.jsonl` (every Claude Code session on this machine) plus
`*/*/subagents/*.jsonl` (the transcripts of spawned agents — `research`, `plan`, `implement`,
`Explore`, `code-review`), attributes each assistant message to a task, and aggregates tokens
and dollar cost. One model response is written to the transcript as several entries sharing
one `usage`; the script counts it once, by `message.id`.

## Routing the request

| User asks | Run |
|---|---|
| «сколько ушло на задачи» / no argument | `--by task` |
| «по проектам» | `--by project` |
| «по фазам» / «research vs implement» | `--by phase` |
| «сколько стоит implement» | `--by phase` (агент важнее навыка в этой колонке) |
| «opus vs sonnet» / «по моделям» | `--by model` |
| «по дням» / «динамика» | `--by day` |
| «сколько на DEV-519» | `--task DEV-519 --by phase` |
| «дашборд» / «покажи наглядно» | `--html <path>` then tell the user to open it |
| «запомни, я работаю над SE-2044» | `--tag SE-2044` |

Other flags: `--since`/`--until` (YYYY-MM-DD), `--project <substring>`, `--model <substring>`,
`--limit N` (default 20), `--json`, `--key-prefixes 'DEV|SE|DF'`.

Show the script's output as-is in a code block — it is already a formatted table. Don't
re-tabulate it. Add one or two sentences of interpretation on top, not a restatement.

## How a task gets attributed

Two sources, in priority order:

1. **Ledger** — `~/.claude/devflow/task-ledger.jsonl`, one JSON line per tagging event
   (`{"ts", "session", "task"}`). `/devflow` appends a line when it routes a task;
   `--tag <KEY>` appends one for the current session.
2. **Heuristic** — Jira keys (`DEV-`/`SE-`/`DF-` by default) mentioned in the user's own
   messages. Tool results and system reminders are excluded.

Both are treated as timestamped markers on the session timeline: a message belongs to the
last marker before it, and the head of a session backfills to its first marker. So one
session covering two tasks splits correctly. Messages in a session with no marker at all
land in `(без задачи)`.

## Reading the numbers

- **Фаза — это агент, а не навык.** У сообщений фазовых агентов в колонке стоит
  `research` / `plan` / `implement`; `attributionAgent` перекрывает `attributionSkill`.
  Расход агента идёт в ту же задачу, что и у родительской сессии.

- **Cache read dominates** every real total — it is billed at 0.1× input, but the volume
  is enormous in long agentic sessions. A large cache-read number is normal, not a leak.
- **Cache write** is 1.25× input at 5-minute TTL and 2× at 1-hour; the script reads the
  actual TTL split out of `usage.cache_creation` rather than assuming.
- **`—` in the phase column** means the work ran in the main session, outside any skill.
  A high `—` share means the pipeline was bypassed for that task.
- Prices are Anthropic list rates per 1M tokens, hardcoded in `PRICES`. Sonnet 5 carries
  an introductory $2/$10 through 2026-08-31; the script bills it at list $3/$15, so
  Sonnet-heavy periods read slightly high. Fast mode is priced separately when
  `usage.speed == "fast"`.
- On a subscription plan the dollar figure is notional — its job is to make opus and
  sonnet comparable on one axis, not to predict an invoice.
