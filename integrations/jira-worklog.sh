#!/usr/bin/env bash
# jira-worklog.sh — запись, правка и удаление своего ворклога (аккаунт — по ключу задачи).
# Без --yes ничего не отправляет, только печатает запрос: реальная запись идёт
# под отдельным ask-правилом в ~/.claude/settings.json.
# Использование:
#   jira-worklog.sh add <KEY> --day YYYY-MM-DD --seconds N [--comment T] [--yes]
#   jira-worklog.sh update <KEY> <ID> [--seconds N] [--comment T] [--yes]
#   jira-worklog.sh delete <KEY> <ID> [--yes]
set -euo pipefail

die() { echo "jira-worklog: $*" >&2; exit 2; }

ACTION="${1:-}"; KEY="${2:-}"
[[ "$ACTION" =~ ^(add|update|delete)$ ]] || die "нужно действие add|update|delete"
[[ "$KEY" =~ ^[A-Za-z][A-Za-z0-9]+-[0-9]+$ ]] || die "нужен ключ задачи, например SE-12"
KEY="${KEY^^}"
shift 2
ID=""
if [ "$ACTION" != add ]; then
  ID="${1:-}"; [[ "$ID" =~ ^[0-9]+$ ]] || die "нужен ID ворклога"; shift
fi

DAY="" SECONDS_="" COMMENT="" HAS_COMMENT=0 APPLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --day) DAY="$2"; shift 2 ;;
    --seconds) SECONDS_="$2"; shift 2 ;;
    --comment) COMMENT="$2"; HAS_COMMENT=1; shift 2 ;;
    --yes) APPLY=1; shift ;;
    *) die "неизвестный аргумент '$1'" ;;
  esac
done

[ -z "$SECONDS_" ] || [[ "$SECONDS_" =~ ^[1-9][0-9]*$ ]] || die "--seconds — целое больше нуля"
case "$ACTION" in
  add)
    [[ "$DAY" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || die "нужен --day YYYY-MM-DD"
    [ -n "$SECONDS_" ] || die "нужен --seconds N" ;;
  update)
    [ -z "$DAY" ] || die "--day при update не поддерживается"
    [ -n "$SECONDS_" ] || [ "$HAS_COMMENT" = 1 ] || die "update: нужен --seconds или --comment" ;;
  delete)
    [ -z "$DAY$SECONDS_" ] && [ "$HAS_COMMENT" = 0 ] || die "delete принимает только --yes" ;;
esac

# shellcheck source=jira-accounts.sh
source "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/jira-accounts.sh"
jira_accounts_load
ACCOUNT="$(jira_account_resolve "$KEY")"
echo "jira-worklog: аккаунт $ACCOUNT" >&2

BASE="/rest/api/2/issue/$KEY/worklog"
payload=$(jq -n --arg day "$DAY" --arg sec "$SECONDS_" --arg comment "$COMMENT" --argjson hc "$HAS_COMMENT" \
  '(if $day != "" then {started: ($day + "T09:00:00.000+0300")} else {} end)
   + (if $sec != "" then {timeSpentSeconds: ($sec | tonumber)} else {} end)
   + (if $hc == 1 then {comment: $comment} else {} end)')
case "$ACTION" in
  add) METHOD=POST; PATH_="$BASE" ;;
  update) METHOD=PUT; PATH_="$BASE/$ID" ;;
  delete) METHOD=DELETE; PATH_="$BASE/$ID"; payload="" ;;
esac

if [ "$APPLY" != 1 ]; then
  echo "DRY RUN — ничего не отправлено. Для записи добавить --yes." >&2
  echo "$METHOD $PATH_"
  [ -z "$payload" ] || echo "$payload" | jq .
  exit 0
fi

request() {
  local out
  out="$(jira_curl "$ACCOUNT" "$@" -w $'\n%{http_code}')" || true
  CODE="${out##*$'\n'}"; BODY="${out%$'\n'*}"
  [ "$BODY" != "$out" ] || BODY=""
}
failed() { echo "jira-worklog: $1 — Jira ответила $CODE:" >&2; echo "$BODY" >&2; exit 1; }

if [ "$ACTION" != add ]; then
  request /rest/api/2/myself
  [[ "$CODE" == 2* ]] || failed "не удалось узнать себя"
  me=$(echo "$BODY" | jq -r '.accountId // empty')
  request "$BASE/$ID"
  [[ "$CODE" == 2* ]] || failed "не удалось прочитать ворклог $ID"
  author=$(echo "$BODY" | jq -r '.author.accountId // empty')
  if [ -z "$me" ] || [ "$author" != "$me" ]; then
    echo "jira-worklog: ворклог $ID в $KEY не ваш — отказ" >&2
    exit 3
  fi
fi

if [ "$ACTION" = delete ]; then
  request "$PATH_" -X DELETE
else
  request "$PATH_" -X "$METHOD" -H 'Content-Type: application/json' -d "$payload"
fi
[[ "$CODE" == 2* ]] || failed "$ACTION не выполнен"
if [ -n "$BODY" ]; then echo "$BODY"; else echo '{}'; fi
