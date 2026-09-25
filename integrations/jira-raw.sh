#!/usr/bin/env bash
# jira-raw.sh — read-only GET к одному ресурсу задачи productsearch Jira, сырой JSON.
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

set -a
# shellcheck disable=SC1090
source "$HOME/.config/devflow/integrations/config.env"
set +a

url="$JIRA_PS_BASE_URL/rest/api/3/issue/$TARGET"
[ -n "$QUERY" ] && url="$url?$QUERY"

curl -sS -X GET -u "$JIRA_PS_EMAIL:$JIRA_PS_API_TOKEN" "$url" | jq -r "$FILTER"
