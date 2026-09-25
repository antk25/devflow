#!/usr/bin/env bash
# Читает ОДИН комментарий Jira productsearch по issue-key и comment-id.
# comment-id берётся из URL (focusedCommentId=...).
# Использование:  jira-comment.sh SE-1945 32745
set -euo pipefail

KEY="${1:?Использование: jira-comment.sh <ISSUE-KEY> <COMMENT-ID>}"
CID="${2:?Использование: jira-comment.sh <ISSUE-KEY> <COMMENT-ID>}"

set -a
# shellcheck disable=SC1090
source "$HOME/.config/devflow/integrations/config.env"
set +a

curl -s -u "$JIRA_PS_EMAIL:$JIRA_PS_API_TOKEN" \
  "$JIRA_PS_BASE_URL/rest/api/3/issue/$KEY/comment/$CID?expand=renderedBody" \
  | jq -r '
      "ISSUE: '"$KEY"'  COMMENT: \(.id)",
      "[\(.author.displayName) @ \(.created)]",
      "",
      (.renderedBody // "(empty)")
    '
