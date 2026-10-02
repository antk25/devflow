---
name: jira
pi: true
description: Read Jira issues, comments and attachments via the read-only shell scripts (never MCP). The account is picked by issue key from config.env. Use whenever you need the text of a Jira task, a specific comment, or an attached screenshot.
user_invocable: true
context: fork
agent: reader
arguments:
  - name: key
    description: "Issue key, e.g. SE-2032 or RS-993"
    required: true
  - name: rest
    description: "Optional: a comment-id to fetch one comment, or 'attachments' to pull images"
    required: false
---

# /jira — read Jira via scripts, not MCP

Fetches issue data, comments and attachments through the read-only helper scripts in
`~/.config/devflow/integrations/`. This is the **only** sanctioned way to read Jira here.

## Golden rule

**NEVER use `mcp__…Atlassian…__*` tools to read a Jira issue.** The MCP grant doesn't cover every
Jira account (`productsearch.atlassian.net` returns *"Cloud id isn't explicitly granted"*). The
scripts below work for every account in `config.env`; don't use `tracker` for reading either.

## Account selection

Accounts (site, token, project keys) live in `~/.config/devflow/integrations/config.env`;
`bash ~/.config/devflow/integrations/jira-accounts.sh check` lists them with access status.

- **Keyed scripts** (`jira-issue.sh`, `jira-comment.sh`, `jira-raw.sh`, `jira-create.sh -P`)
  pick the account by the issue/project key automatically.
- **Unkeyed scripts** (`jira-attachment.sh`, `jira-search.sh`, `jira-jql.sh`) go to the
  **default account** without `--account`. For another account pass it explicitly:
  attachments — `--account <KEY>` (the issue key), JQL — `--account <name>`
  (e.g. `--account productsearch` for `SE` work).

---

## Command: issue (default) — `/jira <KEY>`

Print fields + rendered description + all comments:
```bash
bash ~/.config/devflow/integrations/jira-issue.sh <KEY>
```
Description/comments come as HTML (from `renderedFields`). Read it as-is; don't re-fetch ADF.
If the body references attachments (`…/rest/api/3/attachment/content/<id>`), download the ones
the description or comments refer to when there are only a few (see below); list the rest by id.

## Command: one comment — `/jira <KEY> <COMMENT-ID>`

When a Jira URL has `focusedCommentId=<id>`, read just that comment:
```bash
bash ~/.config/devflow/integrations/jira-comment.sh <KEY> <COMMENT-ID>
```

## Command: attachments — `/jira <KEY> attachments [ID...]`

Screenshots in tickets are attachment ids. Download, then view them with the Read tool
(they're PNGs). **Always pass the issue key** — without it the default account is used and
attachments of other accounts fail:
```bash
bash ~/.config/devflow/integrations/jira-attachment.sh --account <KEY> <ID> [<ID> ...]
# → writes /tmp/jira-attachments/attachment-<ID>.png (one path per line)
```
Then `Read` each printed path to actually see the image. If no ids were given, first run the
issue command and extract the ids from `attachment/content/<id>` in the output.

---

## Notes & fallbacks

- **Read-only.** These scripts cannot post comments, change status, or log time. Do that in
  the web UI. Creating issues is `/jira-create`.
- **Runs in the `reader` subagent** (`context: fork`) in Claude Code: the raw HTML, comments and
  images stay there, the caller gets the digest. Raw text or an image is still one step away for
  the caller — run the script directly or `Read` the attachment path from the digest. pi has no
  subagents and runs the skill in the main context.
- **If a Bash call is denied** by permission policy, return the exact command under `Чего нет`,
  e.g. `bash ~/.config/devflow/integrations/jira-issue.sh SE-2032`, so the caller can run it
  (`!` prefix in the session). Only fall back on an actual denial.
- **Missing creds / 401 / empty output:** run `jira-accounts.sh check` — it shows each account's
  access status with the HTTP code. Don't silently retry via MCP.
