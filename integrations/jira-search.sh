#!/usr/bin/env bash
# Ищет задачи в Jira productsearch по JQL и печатает одну строку на задачу.
# Использование:  jira-search.sh 'project = SE AND text ~ "blog" ORDER BY created DESC' [maxResults]
set -euo pipefail

JQL="${1:?Использование: jira-search.sh <JQL> [maxResults]}"
MAX="${2:-50}"

set -a
# shellcheck disable=SC1090
source "$HOME/.config/devflow/integrations/config.env"
set +a

curl -sS -u "$JIRA_PS_EMAIL:$JIRA_PS_API_TOKEN" -G \
  "$JIRA_PS_BASE_URL/rest/api/3/search/jql" \
  --data-urlencode "jql=$JQL" \
  --data-urlencode "maxResults=$MAX" \
  --data-urlencode "fields=summary,status,assignee,created,updated" \
  | jq -r '
      if (objects | has("errorMessages") or has("errors")) then
        "ERROR: \(.errorMessages // .errors)"
      else
        "TOTAL: \(.issues | length)",
        (.issues[]? |
          "\(.key)  [\(.fields.status.name)]  \(.fields.assignee.displayName // "-")  \(.fields.created[0:10])\n  \(.fields.summary)")
      end
    '
