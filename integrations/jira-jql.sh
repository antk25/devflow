#!/usr/bin/env bash
# jira-jql.sh — read-only постраничный JQL-поиск по productsearch Jira.
# Отличия от jira-search.sh: пагинация (снимает потолок в 100), произвольный
# набор полей, произвольный expand, вывод NDJSON для машинной обработки.
# Только GET, только productsearch, креды берутся из config.env. Ничего не пишет.
# Использование: jira-jql.sh '<JQL>' [fields] [maxTotal] [expand]
set -euo pipefail

JQL="${1:?Использование: jira-jql.sh <JQL> [fields] [maxTotal] [expand]}"
FIELDS="${2:-summary,issuetype,status,resolutiondate,created,updated,assignee,reporter,priority,labels,components,issuelinks,parent,timetracking,timespent,aggregatetimespent,worklog}"
MAXTOTAL="${3:-2000}"
EXPAND="${4:-}"

set -a
# shellcheck disable=SC1090
source "$HOME/.config/devflow/integrations/config.env"
set +a

token=""
got=0
page=0
while :; do
  args=(-sS -u "$JIRA_PS_EMAIL:$JIRA_PS_API_TOKEN" -G
        "$JIRA_PS_BASE_URL/rest/api/3/search/jql"
        --data-urlencode "jql=$JQL"
        --data-urlencode "fields=$FIELDS"
        --data-urlencode "maxResults=100")
  [ -n "$EXPAND" ] && args+=(--data-urlencode "expand=$EXPAND")
  [ -n "$token" ]  && args+=(--data-urlencode "nextPageToken=$token")

  resp="$(curl "${args[@]}")"

  if printf '%s' "$resp" | jq -e '(.errorMessages? // []) | length > 0' >/dev/null 2>&1; then
    printf '%s' "$resp" | jq -r '.errorMessages[]' >&2
    exit 1
  fi

  printf '%s' "$resp" | jq -c '.issues[]?'
  n=$(printf '%s' "$resp" | jq '(.issues // []) | length')
  got=$((got + n))
  page=$((page + 1))

  last="$(printf '%s' "$resp" | jq -r '.isLast // false')"
  token="$(printf '%s' "$resp" | jq -r '.nextPageToken // empty')"
  [ "$n" -eq 0 ] && break
  [ "$last" = "true" ] && break
  [ -z "$token" ] && break
  [ "$got" -ge "$MAXTOTAL" ] && break
  [ "$page" -ge 50 ] && break
done

echo "# jira-jql: fetched=$got pages=$page" >&2
