#!/usr/bin/env bash
# Скачивает вложение(я) Jira productsearch по attachment-id в /tmp/jira-attachments.
# attachment-id берётся из URL картинки (/rest/api/3/attachment/content/<id>).
# Использование:  jira-attachment.sh 30888 30890 30889 30891 30892
set -euo pipefail

set -a
# shellcheck disable=SC1090
source "$HOME/.config/devflow/integrations/config.env"
set +a

OUT_DIR="${JIRA_ATTACH_DIR:-/tmp/jira-attachments}"
mkdir -p "$OUT_DIR"

for ID in "$@"; do
  OUT="$OUT_DIR/attachment-$ID.png"
  curl -s -L -u "$JIRA_PS_EMAIL:$JIRA_PS_API_TOKEN" \
    "$JIRA_PS_BASE_URL/rest/api/3/attachment/content/$ID" -o "$OUT"
  printf '%s\n' "$OUT"
done
