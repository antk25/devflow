#!/usr/bin/env bash
# jira-raw.sh — read-only GET к одному ресурсу задачи Jira (аккаунт — по ключу), сырой JSON.
# Нужен там, где готовые скрипты отбрасывают поля: worklog, changelog (история
# переходов статусов), remotelink (связи с PR), comment.
# Путь жёстко ограничен видом issue/<KEY>[/<sub>], метод всегда GET — записать
# что-либо этим скриптом нельзя.
# Использование: jira-raw.sh <KEY>[/<sub>] [jq-filter] [query-string]
#   jira-raw.sh SE-2144
#   jira-raw.sh SE-2144/changelog '.values[] | .created'
#   jira-raw.sh SE-2144/worklog
set -euo pipefail

TARGET="${1:?Использование: jira-raw.sh <KEY>[/<sub>] [jq-filter] [query]}"
FILTER="${2:-.}"
QUERY="${3:-}"

if ! [[ "$TARGET" =~ ^[A-Za-z]+-[0-9]+(/(changelog|worklog|comment|remotelink|transitions|properties))?$ ]]; then
  echo "jira-raw: путь '$TARGET' не разрешён. Допустимо: <KEY> или <KEY>/{changelog,worklog,comment,remotelink,transitions,properties}" >&2
  exit 2
fi

# shellcheck source=jira-accounts.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/jira-accounts.sh"
jira_accounts_load
ACCOUNT="$(jira_account_resolve "${TARGET%%/*}")"

path="/rest/api/3/issue/$TARGET"
[ -n "$QUERY" ] && path="$path?$QUERY"

jira_curl "$ACCOUNT" "$path" -S -X GET | jq -r "$FILTER"
