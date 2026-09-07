---
name: jira
description: Read Jira issues, comments and attachments via the read-only shell scripts (never MCP). Routes SE-* to productsearch.atlassian.net, everything else to resolventa.atlassian.net. Use whenever you need the text of a Jira task, a specific comment, or an attached screenshot.
user_invocable: true
arguments:
  - name: key
    description: "Issue key, e.g. SE-2032 (or RS-993 for the resolventa instance)"
    required: true
  - name: rest
    description: "Optional: a comment-id to fetch one comment, or 'attachments' to pull images"
    required: false
---

# /jira — read Jira via scripts, not MCP

Fetches issue data, comments and attachments through the read-only helper scripts in
`~/.config/devflow/integrations/`. This is the **only** sanctioned way to read Jira here.

## Golden rule

**NEVER use `mcp__…Atlassian…__*` tools to read a Jira issue.** The MCP grant covers
`resolventa.atlassian.net` only; `productsearch.atlassian.net` (all `SE-*` issues — the green
project) returns *"Cloud id isn't explicitly granted"*. The scripts below are the canonical path
and work for SE-* directly. If you catch yourself reaching for an Atlassian MCP tool to read a
ticket, stop and use this skill instead.

## Instance routing (by key prefix)

- **`SE-*`** → `productsearch.atlassian.net` (M:AI Product Search). Use the `jira-*.sh` scripts —
  they source `JIRA_PS_*` creds from `config.env`. This is the default for the green project.
- **anything else** (`RS-*`, `DEV-*`, …) → `resolventa.atlassian.net`. Use the `tracker` CLI
  (`tracker jira issue get --key <KEY>`), which reads the default `JIRA_*` creds. Still no MCP.

Config for both lives in `~/.config/devflow/integrations/config.env` (two token pairs:
`JIRA_*` = resolventa, `JIRA_PS_*` = productsearch).

---

## Command: issue (default) — `/jira <KEY>`

Print fields + rendered description + all comments.

- **SE-\*:**
  ```bash
  bash ~/.config/devflow/integrations/jira-issue.sh <KEY>
  ```
- **other:**
  ```bash
  tracker jira issue get --key <KEY>
  tracker jira issue comments --key <KEY>   # comments are a separate call here
  ```

The SE-* script renders description/comments as HTML (from `renderedFields`). Read it as-is;
don't try to re-fetch ADF. If the body references attachments
(`…/rest/api/3/attachment/content/<id>`), note the ids — offer to pull them (see below).

## Command: one comment — `/jira <KEY> <COMMENT-ID>`

When a Jira URL has `focusedCommentId=<id>`, read just that comment (SE-* only):
```bash
bash ~/.config/devflow/integrations/jira-comment.sh <KEY> <COMMENT-ID>
```

## Command: attachments — `/jira <KEY> attachments [ID...]`

Screenshots in tickets are attachment ids. Download, then view them with the Read tool
(they're PNGs). SE-* only:
```bash
bash ~/.config/devflow/integrations/jira-attachment.sh <ID> [<ID> ...]
# → writes /tmp/jira-attachments/attachment-<ID>.png (one path per line)
```
Then `Read` each printed path to actually see the image. If no ids were given, first run the
issue command and extract the ids from `attachment/content/<id>` in the output.

---

## Notes & fallbacks

- **Read-only.** These scripts/CLI cannot post comments, change status, or log time. Do that in
  the web UI. (`tracker` technically has create/update for resolventa, but treat writes as manual
  unless the user explicitly asks.)
- **If a Bash call is denied** by permission policy, hand the exact command to the user under the
  `!` prefix, e.g. `! bash ~/.config/devflow/integrations/jira-issue.sh SE-2032` — it runs in the
  session and the output lands in the conversation. (As of 2026-07-13 the assistant can run these
  directly; only fall back to `!` on an actual denial.)
- **Missing creds / 401 / empty output:** check `config.env` exists and the relevant token pair is
  set. Don't silently retry via MCP.
