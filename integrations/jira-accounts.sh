#!/usr/bin/env bash
# Аккаунты Jira из config.env: выбор по ключу задачи, ключу проекта или имени.
# Подключение:  source jira-accounts.sh; jira_accounts_load
# Прямой запуск: jira-accounts.sh check — проверка доступа каждого аккаунта (только GET).
# Токен уходит в curl через stdin (-K -), поэтому не виден в argv.

_JIRA_ACCOUNTS=()
_JIRA_DEFAULT=""

_jira_die() { echo "jira-accounts: $*" >&2; exit 2; }

_jira_var() { local v="JIRA_${1^^}_$2"; printf '%s' "${!v:-}"; }

jira_accounts_load() {
  local cfg="${DEVFLOW_JIRA_CONFIG:-$HOME/.config/devflow/integrations/config.env}"
  [ -r "$cfg" ] || _jira_die "нет файла $cfg"
  # shellcheck disable=SC1090
  source "$cfg"

  if [ -n "${JIRA_ACCOUNTS:-}" ]; then
    read -r -a _JIRA_ACCOUNTS <<< "$JIRA_ACCOUNTS"
    _JIRA_DEFAULT="${JIRA_DEFAULT_ACCOUNT:-}"
  else
    _JIRA_ACCOUNTS=()
    if [ -n "${JIRA_BASE_URL:-}" ]; then
      JIRA_RESOLVENTA_BASE_URL="$JIRA_BASE_URL"
      JIRA_RESOLVENTA_EMAIL="${JIRA_EMAIL:-}"
      JIRA_RESOLVENTA_API_TOKEN="${JIRA_API_TOKEN:-}"
      JIRA_RESOLVENTA_PROJECTS=""
      _JIRA_ACCOUNTS+=(resolventa)
      _JIRA_DEFAULT=resolventa
    fi
    if [ -n "${JIRA_PS_BASE_URL:-}" ]; then
      JIRA_PRODUCTSEARCH_BASE_URL="$JIRA_PS_BASE_URL"
      JIRA_PRODUCTSEARCH_EMAIL="${JIRA_PS_EMAIL:-}"
      JIRA_PRODUCTSEARCH_API_TOKEN="${JIRA_PS_API_TOKEN:-}"
      JIRA_PRODUCTSEARCH_PROJECTS="SE"
      _JIRA_ACCOUNTS+=(productsearch)
    fi
  fi
  [ "${#_JIRA_ACCOUNTS[@]}" -gt 0 ] || _jira_die "в $cfg нет ни одного аккаунта Jira"

  local name field key owner
  declare -A owners=()
  for name in "${_JIRA_ACCOUNTS[@]}"; do
    [[ "$name" =~ ^[a-z][a-z0-9_]*$ ]] || _jira_die "недопустимое имя аккаунта '$name'"
    for field in BASE_URL EMAIL API_TOKEN; do
      [ -n "$(_jira_var "$name" "$field")" ] || _jira_die "аккаунт $name: нет поля JIRA_${name^^}_$field"
    done
    for key in $(_jira_var "$name" PROJECTS); do
      owner="${owners[$key]:-}"
      [ -z "$owner" ] || _jira_die "ключ $key у аккаунтов $owner и $name"
      owners[$key]="$name"
    done
  done
  if [ -n "$_JIRA_DEFAULT" ] && ! _jira_known "$_JIRA_DEFAULT"; then
    _jira_die "JIRA_DEFAULT_ACCOUNT=$_JIRA_DEFAULT нет среди аккаунтов: ${_JIRA_ACCOUNTS[*]}"
  fi
}

_jira_known() {
  local n
  for n in "${_JIRA_ACCOUNTS[@]}"; do [ "$n" = "$1" ] && return 0; done
  return 1
}

jira_accounts_list() { printf '%s\n' "${_JIRA_ACCOUNTS[@]}"; }

jira_account_resolve() {
  local ref="${1:?jira_account_resolve: нужен ключ или имя}" name key k
  if _jira_known "$ref"; then printf '%s\n' "$ref"; return; fi
  key="${ref%%-*}"
  key="${key^^}"
  for name in "${_JIRA_ACCOUNTS[@]}"; do
    for k in $(_jira_var "$name" PROJECTS); do
      [ "${k^^}" = "$key" ] && { printf '%s\n' "$name"; return; }
    done
  done
  [ -n "$_JIRA_DEFAULT" ] || _jira_die "ключ $key не принадлежит ни одному аккаунту"
  printf '%s\n' "$_JIRA_DEFAULT"
}

jira_account_field() {
  case "$2" in
    BASE_URL|EMAIL|PROJECTS) _jira_var "$1" "$2"; echo ;;
    *) _jira_die "поле $2 не отдаётся" ;;
  esac
}

_jira_credentials() {
  local user="$(_jira_var "$1" EMAIL):$(_jira_var "$1" API_TOKEN)"
  user="${user//\\/\\\\}"
  printf 'user = "%s"\n' "${user//\"/\\\"}"
}

jira_curl() {
  local name="$1" path="$2"
  shift 2
  _jira_known "$name" || _jira_die "нет аккаунта $name"
  _jira_credentials "$name" | curl -s -K - --url "$(_jira_var "$name" BASE_URL)$path" "$@"
}

jira_curl_status() {
  local out
  out="$(jira_curl "$1" "$2" -w $'\n%{http_code}')" || true
  printf '%s\t%s\n' "${out##*$'\n'}" "${out%$'\n'*}"
}

_jira_check() {
  local name out code body who failed=0
  jira_accounts_load
  printf '%s\t%s\t%s\t%s\t%s\n' "АККАУНТ" "URL" "EMAIL" "КЛЮЧИ" "ДОСТУП"
  for name in "${_JIRA_ACCOUNTS[@]}"; do
    out="$(jira_curl_status "$name" /rest/api/3/myself)"
    code="${out%%$'\t'*}"
    body="${out#*$'\t'}"
    if [ "$code" = 200 ]; then
      who="$(jq -r '.displayName // .emailAddress // "?"' <<< "$body" 2>/dev/null || echo "?")"
    else
      who="нет доступа (HTTP ${code:-?})"
      failed=1
    fi
    [ "$name" = "$_JIRA_DEFAULT" ] && name="$name*"
    printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$(_jira_var "${name%\*}" BASE_URL)" \
      "$(_jira_var "${name%\*}" EMAIL)" "$(_jira_var "${name%\*}" PROJECTS)" "$who"
  done
  return "$failed"
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -euo pipefail
  case "${1:-}" in
    check) _jira_check ;;
    *) echo "Использование: jira-accounts.sh check" >&2; exit 2 ;;
  esac
fi
