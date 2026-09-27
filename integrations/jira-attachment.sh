#!/usr/bin/env bash
# Скачивает вложение(я) Jira по attachment-id в /tmp/jira-attachments.
# Аккаунт — по ключу задачи или имени через --account, без него — по умолчанию.
# attachment-id берётся из URL картинки (/rest/api/3/attachment/content/<id>).
# Использование:  jira-attachment.sh [--account <ключ|имя>] 30888 30890 30889 30891 30892
set -euo pipefail

ACCOUNT=""
if [ "${1:-}" = "--account" ]; then ACCOUNT="${2:?--account: нужно имя}"; shift 2; fi
# shellcheck source=jira-accounts.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/jira-accounts.sh"
jira_accounts_load
ACCOUNT="$(jira_account_resolve "${ACCOUNT:-${_JIRA_DEFAULT:-$(jira_accounts_list | head -n1)}}")"

OUT_DIR="${JIRA_ATTACH_DIR:-/tmp/jira-attachments}"
mkdir -p "$OUT_DIR"

for ID in "$@"; do
  OUT="$OUT_DIR/attachment-$ID.png"
  jira_curl "$ACCOUNT" "/rest/api/3/attachment/content/$ID" -L -o "$OUT"
  printf '%s\n' "$OUT"
done
