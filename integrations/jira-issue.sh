#!/usr/bin/env bash
# Читает задачу Jira productsearch и печатает поля/описание/комментарии.
# Использование:  jira-issue.sh SE-1983
set -euo pipefail

KEY="${1:?Использование: jira-issue.sh <ISSUE-KEY>}"

set -a
# shellcheck disable=SC1090
source "$HOME/.config/devflow/integrations/config.env"
set +a

curl -s -u "$JIRA_PS_EMAIL:$JIRA_PS_API_TOKEN" \
  "$JIRA_PS_BASE_URL/rest/api/3/issue/$KEY?expand=renderedFields" \
  | jq -r '
      "KEY: \(.key)",
      "SUMMARY: \(.fields.summary)",
      "STATUS: \(.fields.status.name)  PRIORITY: \(.fields.priority.name // "-")  TYPE: \(.fields.issuetype.name)",
      "ASSIGNEE: \(.fields.assignee.displayName // "-")  REPORTER: \(.fields.reporter.displayName // "-")",
      "CREATED: \(.fields.created)  UPDATED: \(.fields.updated)",
      "LINKS: \([.fields.issuelinks[]? | if .outwardIssue then "\(.type.outward) \(.outwardIssue.key)" else "\(.type.inward) \(.inwardIssue.key)" end] | join(", "))",
      "",
      "--- DESCRIPTION ---",
      (.renderedFields.description // "(empty)"),
      "",
      "--- COMMENTS (\(.fields.comment.comments | length)) ---",
      (.renderedFields.comment.comments[]? | "[\(.author.displayName) @ \(.created)]\n\(.body)\n")
    '
