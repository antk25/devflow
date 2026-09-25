#!/usr/bin/env bash
# jira-create.sh — создание задачи в Jira (инстанс JIRA_PS_* из config.env).
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

set -a
# shellcheck disable=SC1090
source "$HOME/.config/devflow/integrations/config.env"
set +a
AUTH="$JIRA_PS_EMAIL:$JIRA_PS_API_TOKEN"

if [ "$TYPES" = 1 ]; then
  curl -sS -u "$AUTH" "$JIRA_PS_BASE_URL/rest/api/2/issue/createmeta/$PROJECT/issuetypes" \
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

resp=$(curl -sS -u "$AUTH" -H 'Content-Type: application/json' \
  -d "$payload" "$JIRA_PS_BASE_URL/rest/api/2/issue")
key=$(echo "$resp" | jq -r '.key // empty')
if [ -z "$key" ]; then
  echo "jira-create: Jira отказала:" >&2
  echo "$resp" | jq . >&2
  exit 1
fi
echo "$key $JIRA_PS_BASE_URL/browse/$key"
