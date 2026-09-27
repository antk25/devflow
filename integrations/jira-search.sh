#!/usr/bin/env bash
# Ищет задачи в Jira по JQL (аккаунт — --account, без него — по умолчанию) и печатает одну строку на задачу.
# Использование:  jira-search.sh [--account <имя>] 'project = SE AND text ~ "blog" ORDER BY created DESC' [maxResults]
set -euo pipefail

ACCOUNT=""
if [ "${1:-}" = "--account" ]; then ACCOUNT="${2:?--account: нужно имя}"; shift 2; fi

JQL="${1:?Использование: jira-search.sh <JQL> [maxResults]}"
MAX="${2:-50}"

# shellcheck source=jira-accounts.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/jira-accounts.sh"
jira_accounts_load
ACCOUNT="$(jira_account_resolve "${ACCOUNT:-${_JIRA_DEFAULT:-$(jira_accounts_list | head -n1)}}")"

jira_curl "$ACCOUNT" /rest/api/3/search/jql -S -G \
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
