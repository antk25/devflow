#!/usr/bin/env bash
# Читает ОДИН комментарий Jira (аккаунт — по ключу) по issue-key и comment-id.
# comment-id берётся из URL (focusedCommentId=...).
# Использование:  jira-comment.sh SE-1945 32745
set -euo pipefail

KEY="${1:?Использование: jira-comment.sh <ISSUE-KEY> <COMMENT-ID>}"
CID="${2:?Использование: jira-comment.sh <ISSUE-KEY> <COMMENT-ID>}"

# shellcheck source=jira-accounts.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/jira-accounts.sh"
jira_accounts_load
ACCOUNT="$(jira_account_resolve "$KEY")"

jira_curl "$ACCOUNT" "/rest/api/3/issue/$KEY/comment/$CID?expand=renderedBody" \
  | jq -r '
      "ISSUE: '"$KEY"'  COMMENT: \(.id)",
      "[\(.author.displayName) @ \(.created)]",
      "",
      (.renderedBody // "(empty)")
    '
