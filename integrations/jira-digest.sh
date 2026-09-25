#!/usr/bin/env bash
# jira-digest.sh — «мои задачи: что нового с прошлого раза» по обоим Jira-инстансам.
# Сверху — корзина «ждут тебя»: задачи, где последний комментарий не твой, старейшие первыми.
# Корзина считается по всем полученным задачам, а не только по изменившимся: она стоячая,
# и задача, которую ты видел, но не ответил, из неё не исчезает.
# resolventa (JIRA_*) + productsearch (JIRA_PS_*). Дифф по jira-seen.json.
#
# Использование:
#   jira-digest.sh          # печатает дайджест и отмечает показанное (двигает state)
#   jira-digest.sh --peek   # печатает, но state НЕ двигает («просто гляну»)
#
# Первый запуск (нет jira-seen.json): окно 7 дней. Yandex Tracker не подключается.
set -euo pipefail

INTEGRATIONS_DIR="$HOME/.config/devflow/integrations"
CONFIG_FILE="$INTEGRATIONS_DIR/config.env"
SEEN_FILE="$INTEGRATIONS_DIR/jira-seen.json"

PEEK=0
[[ "${1:-}" == "--peek" ]] && PEEK=1

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "error: config not found: $CONFIG_FILE" >&2
    exit 1
fi
set -a
# shellcheck disable=SC1090
source "$CONFIG_FILE"
set +a

# --- Load state ---
FIRST_RUN=0
if [[ -f "$SEEN_FILE" ]]; then
    SEEN_JSON="$(cat "$SEEN_FILE")"
    echo "$SEEN_JSON" | jq -e . >/dev/null 2>&1 || SEEN_JSON="{}"
else
    FIRST_RUN=1
    SEEN_JSON="{}"
fi
NEW_STATE="$SEEN_JSON"

# Секции инстансов копятся здесь, чтобы корзина печаталась перед ними.
DIGEST_OUT=""
BUCKET=""

# Первый запуск показывает только последние 7 дней (сравнение по дате, offset неважен);
# при этом high-water пишется по всем полученным задачам, чтобы 2-й прогон не вываливал бэклог.
CUTOFF_DATE="$(date -d '7 days ago' +%Y-%m-%d)"
FIRST_JSON=$([[ "$FIRST_RUN" == "1" ]] && echo true || echo false)

# --- Render one instance; updates global NEW_STATE as a side effect ---
digest_instance() {
    local label="$1" base="$2" email="$3" token="$4"

    if [[ -z "$base" || -z "$email" || -z "$token" ]]; then
        DIGEST_OUT+="═══ $label ═══"$'\n'"  warn: креды не заданы в config.env — пропуск"$'\n\n'
        return 0
    fi

    local me=""
    me=$(curl -sS -u "$email:$token" "$base/rest/api/3/myself" 2>/dev/null \
        | jq -r '.accountId // ""' 2>/dev/null) || me=""

    local jql="assignee = currentUser() ORDER BY updated DESC"

    local resp
    resp=$(curl -sS -u "$email:$token" -G "$base/rest/api/3/search/jql" \
        --data-urlencode "jql=$jql" \
        --data-urlencode "maxResults=50" \
        --data-urlencode "fields=summary,status,updated,comment") || {
        DIGEST_OUT+="═══ $label ═══"$'\n'"  warn: запрос не удался (сеть/креды)"$'\n\n'
        return 0
    }

    if echo "$resp" | jq -e 'objects | has("errorMessages") or has("errors")' >/dev/null 2>&1; then
        DIGEST_OUT+="═══ $label ═══"$'\n'"  warn: API: $(echo "$resp" | jq -rc '.errorMessages // .errors // "unknown"')"$'\n\n'
        return 0
    fi

    # High-water: запомнить updated по всем полученным задачам
    local inst_map
    inst_map=$(echo "$resp" | jq -c 'reduce (.issues[]?) as $i ({}; .[$i.key] = $i.fields.updated)')
    NEW_STATE=$(jq -cn --argjson a "$NEW_STATE" --argjson b "$inst_map" '$a * $b')

    local render
    render=$(echo "$resp" | jq -r --argjson seen "$SEEN_JSON" --arg me "$me" \
        --arg cutoff "$CUTOFF_DATE" --argjson first "$FIRST_JSON" '
        def adftext: [recurse(.content[]?) | select(.type=="text") | .text] | join(" ") | gsub("\\s+";" ") | gsub("^ +| +$";"");
        def short($t): if ($t|length) > 280 then ($t[0:280] + "…") else $t end;
        .issues // []
        | map(
            . as $i
            | ($i.fields.updated) as $u
            | ($seen[$i.key]) as $s
            | (if $s != null then (if $u > $s then "UPD" else "SKIP" end)
               elif ($first and ($u[0:10] < $cutoff)) then "SKIP"
               else "NEW" end) as $st
            | select($st != "SKIP")
            | ($i.fields.comment.comments // []) as $all
            | (if $s == null then $all[-5:] else [ $all[] | select((.updated // .created) > $s) ] end) as $nc
            | {k:$i.key, st:$st, status:$i.fields.status.name, sum:$i.fields.summary, u:$u, total:($all|length), nc:$nc}
          )
        | .[]
        | "",
          "▸ \(.k)  [\(.status)]  · \(.st)",
          "  \(.sum)",
          ("  upd \(.u[0:16] | sub("T";" "))" + (if .st=="NEW" and .total>5 then "  (последние 5 из \(.total))" else "" end)),
          (if (.nc|length)==0 and .st=="UPD" then "  · изменены описание/поля (новых комментариев нет)" else empty end),
          ( .nc[]?
            | (.body | adftext) as $txt
            | "  ┌ \(.author.displayName)\(if .author.accountId==$me then " (ты)" else "" end) · \(.created[0:16] | sub("T";" "))",
              "  └ \(short($txt))"
          )
    ')

    # «Ждут тебя» — по ВСЕМ полученным задачам, до фильтра SKIP: последний комментарий не твой.
    # Одна строка на задачу, ISO-метка впереди — по ней потом сортировка старейшим первым.
    if [[ -z "$me" ]]; then
        # Без accountId «свой/чужой» не отличить — корзину по этому инстансу не строим, но и
        # не делаем вид, что она пуста.
        DIGEST_OUT+="  warn: accountId не определён ($base/rest/api/3/myself) — корзина «ждут тебя» по $label пропущена"$'\n'
    else
        local bucket_render
        bucket_render=$(echo "$resp" | jq -r --arg me "$me" --argjson now "$(date +%s)" '
            def days($t): (try ((($now - (($t[0:19] + "Z") | fromdateiso8601)) / 86400) | floor) catch 0);
            .issues // []
            | map(select((.fields.comment.comments // []) | length > 0))
            | map(. as $i | ($i.fields.comment.comments[-1]) as $c
                | select($c.author.accountId != $me)
                | {k: $i.key, status: $i.fields.status.name, sum: $i.fields.summary,
                   who: $c.author.displayName, at: ($c.created // "")}
              )
            | .[]
            | "\(.at)\t\(.k)  [\(.status)]  · ждёт \(days(.at)) дн · \(.who), \(.at[0:16] | sub("T";" "))\t\(.sum)"
        ') || bucket_render=""
        [[ -n "$bucket_render" ]] && BUCKET+="$bucket_render"$'\n'
    fi

    DIGEST_OUT+="═══ $label ═══"$'\n'
    if [[ -z "$render" ]]; then
        DIGEST_OUT+="  нового нет"$'\n'
    else
        DIGEST_OUT+="$render"$'\n'
    fi
    DIGEST_OUT+=$'\n'
    return 0
}

echo "Jira-дайджест — новое с прошлого раза$([[ "$FIRST_RUN" == "1" ]] && echo " (первый запуск: окно 7 дней)")"
echo ""

digest_instance "resolventa" "${JIRA_BASE_URL:-}" "${JIRA_EMAIL:-}" "${JIRA_API_TOKEN:-}"
digest_instance "productsearch" "${JIRA_PS_BASE_URL:-}" "${JIRA_PS_EMAIL:-}" "${JIRA_PS_API_TOKEN:-}"

echo "⏳ ждут тебя — последний комментарий не твой, старейшие сверху"
if [[ -n "$BUCKET" ]]; then
    printf '%s' "$BUCKET" | sort | cut -f2- | while IFS=$'\t' read -r head sum; do
        echo "  ▸ $head"
        echo "    $sum"
    done
else
    echo "  пусто — мяч не на твоей стороне"
fi
echo ""

printf '%s' "$DIGEST_OUT"

# --- Persist state (unless --peek) ---
if [[ "$PEEK" == "0" ]]; then
    tmp=$(mktemp)
    printf '%s\n' "$NEW_STATE" | jq '.' > "$tmp" && mv "$tmp" "$SEEN_FILE"
else
    echo "(--peek: state не изменён)"
fi
