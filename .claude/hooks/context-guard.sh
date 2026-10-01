#!/usr/bin/env bash
# UserPromptSubmit: the model can't see the status line, so the cut threshold is passed to it here —
# it then offers /cut at the end of a step instead of auto-compaction firing mid-edit.
python3 -c '
import json, sys
try:
    path = json.load(sys.stdin).get("transcript_path") or ""
    lines = open(path, encoding="utf-8").read().splitlines()
except Exception:
    sys.exit(0)
for line in reversed(lines):
    try:
        u = json.loads(line)["message"]["usage"]
    except Exception:
        continue
    tok = u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
    break
else:
    sys.exit(0)
k = tok // 1000
if tok >= 180000:
    print(f"CONTEXT_CUT {k}K: не начинай новую большую работу. Доведи текущее действие до точки, где его можно передать, и первым делом предложи /cut.")
elif tok >= 120000:
    print(f"CONTEXT_WARN {k}K: когда закончишь текущий шаг, предложи /cut, а не начинай следующий в этой сессии.")
' 2>/dev/null || true
