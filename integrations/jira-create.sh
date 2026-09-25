#!/usr/bin/env bash
# jira-create.sh — создание задачи в Jira (аккаунт — по ключу проекта -P).
# Без --yes ничего не отправляет, только печатает запрос: реальная запись идёт
# под отдельным ask-правилом в ~/.claude/settings.json.
# Описание — файл в wiki-разметке Jira (API v2 принимает её строкой, ADF не нужен).
# Использование:
#   jira-create.sh -P <PROJECT> --types                 # доступные типы задач проекта
#   jira-create.sh -P <PROJECT> -s "<summary>" -d <desc-file> [-t Task] [-p <PARENT-KEY>] [-l label]... [--yes]
set -euo pipefail

PROJECT=""
TYPE="Task"
SUMMARY=""
DESC_FILE=""
PARENT=""
LABELS=()
APPLY=0
TYPES=0

while [ $# -gt 0 ]; do
  case "$1" in
    -P) PROJECT="$2"; shift 2 ;;
    -s) SUMMARY="$2"; shift 2 ;;
    -d) DESC_FILE="$2"; shift 2 ;;
    -t) TYPE="$2"; shift 2 ;;
    -p) PARENT="$2"; shift 2 ;;
    -l) LABELS+=("$2"); shift 2 ;;
    --yes) APPLY=1; shift ;;
    --types) TYPES=1; shift ;;
    *) echo "jira-create: неизвестный аргумент '$1'" >&2; exit 2 ;;
  esac
done

[[ "$PROJECT" =~ ^[A-Z][A-Z0-9]+$ ]] || { echo "jira-create: нужен -P <PROJECT>, например -P SE" >&2; exit 2; }

# shellcheck source=jira-accounts.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/jira-accounts.sh"
jira_accounts_load
ACCOUNT="$(jira_account_resolve "$PROJECT")"
echo "jira-create: аккаунт $ACCOUNT" >&2

if [ "$TYPES" = 1 ]; then
  jira_curl "$ACCOUNT" "/rest/api/2/issue/createmeta/$PROJECT/issuetypes" -S \
    | jq -r '.issueTypes // .values | .[] | "\(.id)\t\(.name)\(if .subtask then " (subtask)" else "" end)"'
  exit 0
fi

[ -n "$SUMMARY" ] || { echo "jira-create: нужен -s <summary>" >&2; exit 2; }
[ -f "$DESC_FILE" ] || { echo "jira-create: нужен -d <файл описания>" >&2; exit 2; }
if [ -n "$PARENT" ] && ! [[ "$PARENT" =~ ^$PROJECT-[0-9]+$ ]]; then
  echo "jira-create: родитель должен быть $PROJECT-<n>" >&2; exit 2
fi

labels_json=$(printf '%s\n' "${LABELS[@]+"${LABELS[@]}"}" | jq -R . | jq -sc 'map(select(. != ""))')

payload=$(jq -n \
  --arg project "$PROJECT" --arg type "$TYPE" --arg summary "$SUMMARY" \
  --rawfile description "$DESC_FILE" --arg parent "$PARENT" --argjson labels "$labels_json" \
  '{fields: ({project: {key: $project}, issuetype: {name: $type}, summary: $summary, description: $description}
    + (if $parent != "" then {parent: {key: $parent}} else {} end)
    + (if ($labels | length) > 0 then {labels: $labels} else {} end))}')

if [ "$APPLY" != 1 ]; then
  echo "DRY RUN — ничего не отправлено. Для создания добавить --yes." >&2
  echo "$payload" | jq .
  exit 0
fi

resp=$(jira_curl "$ACCOUNT" /rest/api/2/issue -S -H 'Content-Type: application/json' -d "$payload")
key=$(echo "$resp" | jq -r '.key // empty')
if [ -z "$key" ]; then
  echo "jira-create: Jira отказала:" >&2
  echo "$resp" | jq . >&2
  exit 1
fi
echo "$key $(jira_account_field "$ACCOUNT" BASE_URL)/browse/$key"
