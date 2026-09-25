#!/usr/bin/env python3
"""token-stats.py — статистика расхода токенов по задачам, проектам, фазам и моделям.

Источник — транскрипты Claude Code: сессии ~/.claude/projects/*/*.jsonl и транскрипты
фазовых агентов ~/.claude/projects/*/*/subagents/*.jsonl. Привязка к задаче: журнал
~/.claude/devflow/task-ledger.jsonl (приоритет), иначе упоминания ключа в сообщениях
пользователя.
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from devflow.transcripts import (LEDGER, PROJECTS_ROOT, assign_tasks, load_ledger,  # noqa: E402
                                 parse_ts, project_of, user_text)

# $ за 1M токенов, прайс-лист Anthropic. cache write ×1.25 (5m) / ×2.0 (1h), cache read ×0.1.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5-1": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-opus-4-5": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0),  # интро-цена $2/$10 действует до 2026-08-31
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
FAST_PRICES = {"claude-opus-5": (10.0, 50.0), "claude-opus-4-8": (10.0, 50.0)}
DEFAULT_PRICE = (5.0, 25.0)

METRICS = ("input", "output", "cache_write", "cache_read", "cost")


def price_for(model, speed):
    if speed == "fast" and model in FAST_PRICES:
        return FAST_PRICES[model]
    return PRICES.get(model, DEFAULT_PRICE)


def scan(root, key_re, ledger):
    """Читает транскрипты и возвращает список записей ассистентских сообщений."""
    records, seen_msgs = [], set()
    paths = sorted([*root.glob("*/*.jsonl"), *root.glob("*/*/subagents/*.jsonl")])
    for path in paths:
        # транскрипт субагента лежит в <сессия>/subagents/ — задача у него общая с родителем
        stem = path.parent.parent.name if path.parent.name == "subagents" else path.stem
        msgs, marks, seen_sids = [], list(ledger.get(stem, [])), set()
        for line in path.open(encoding="utf-8", errors="ignore"):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            kind = entry.get("type")
            ts = parse_ts(entry.get("timestamp"))
            if kind == "user":
                for m in key_re.finditer(user_text(entry.get("message", {}))[:8000]):
                    marks.append((ts, m.group(0).upper()))
            elif kind == "assistant":
                msg = entry.get("message", {})
                # один ответ модели пишется несколькими записями (thinking, tool_use,
                # text) с одним и тем же usage — считать его можно только раз
                msg_id = msg.get("id")
                if msg_id:
                    if msg_id in seen_msgs:
                        continue
                    seen_msgs.add(msg_id)
                usage = msg.get("usage") or {}
                created = usage.get("cache_creation") or {}
                cw_1h = created.get("ephemeral_1h_input_tokens", 0)
                cw_5m = created.get("ephemeral_5m_input_tokens", 0)
                if not created:
                    cw_5m = usage.get("cache_creation_input_tokens", 0)
                seen_sids.add(entry.get("sessionId") or stem)
                model = msg.get("model") or "?"
                p_in, p_out = price_for(model, usage.get("speed"))
                tok_in = usage.get("input_tokens", 0)
                tok_out = usage.get("output_tokens", 0)
                tok_cr = usage.get("cache_read_input_tokens", 0)
                cost = (tok_in * p_in + tok_out * p_out
                        + cw_5m * p_in * 1.25 + cw_1h * p_in * 2.0
                        + tok_cr * p_in * 0.1) / 1_000_000
                msgs.append({
                    "ts": ts,
                    "day": ts.astimezone(timezone.utc).strftime("%Y-%m-%d") if ts else "?",
                    "session": entry.get("sessionId") or stem,
                    "project": project_of(entry.get("cwd")),
                    "model": model,
                    "phase": (entry.get("attributionAgent")
                              or entry.get("attributionSkill") or "—"),
                    "input": tok_in,
                    "output": tok_out,
                    "cache_write": cw_5m + cw_1h,
                    "cache_read": tok_cr,
                    "cost": cost,
                })
        # у возобновлённой сессии sessionId внутри записей не совпадает с именем файла
        for sid in seen_sids - {stem}:
            marks.extend(ledger.get(sid, []))
        assign_tasks(msgs, marks)
        records.extend(msgs)
    return records


def aggregate(records, key):
    buckets = defaultdict(lambda: dict.fromkeys(METRICS, 0.0))
    sessions = defaultdict(set)
    phases = defaultdict(lambda: defaultdict(float))
    for r in records:
        b = buckets[r[key]]
        for metric in METRICS:
            b[metric] += r[metric]
        sessions[r[key]].add(r["session"])
        phases[r[key]][r["phase"]] += r["cost"]
    rows = []
    for name, b in buckets.items():
        top = sorted(phases[name].items(), key=lambda kv: -kv[1])[:3]
        total = sum(phases[name].values()) or 1
        rows.append({
            "name": name, **b,
            "sessions": len(sessions[name]),
            "phases": [(p, round(100 * c / total)) for p, c in top],
        })
    return rows


def human(n):
    n = float(n)
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= limit:
            return f"{n / limit:.2f}{suffix}"
    return f"{n:.0f}"


TITLES = {"task": "ЗАДАЧА", "project": "ПРОЕКТ", "phase": "ФАЗА",
          "model": "МОДЕЛЬ", "day": "ДЕНЬ", "session": "СЕССИЯ"}


def short(name, limit=44):
    """Обрезает слева — у путей и id различимый хвост, а не начало."""
    name = str(name)
    return name if len(name) <= limit else "…" + name[-(limit - 1):]


def render_text(rows, key, limit, totals):
    rows = (sorted(rows, key=lambda r: r["name"], reverse=True) if key == "day"
            else sorted(rows, key=lambda r: -r["cost"]))
    shown = rows[:limit]
    with_phases = key != "phase"
    width = max([len(TITLES[key])] + [len(short(r["name"])) for r in shown])
    head = (f"{TITLES[key]:<{width}}  {'OUT':>8} {'CACHE-W':>8} {'CACHE-R':>9} "
            f"{'$':>8}  {'СЕС':>3}" + ("  ФАЗЫ" if with_phases else ""))
    out = [head, "─" * len(head)]
    for r in shown:
        phases = (" " + " ".join(f"{p}:{pct}%" for p, pct in r["phases"] if pct >= 5)
                  if with_phases else "")
        out.append(f"{short(r['name']):<{width}}  {human(r['output']):>8} "
                   f"{human(r['cache_write']):>8} {human(r['cache_read']):>9} "
                   f"{r['cost']:>8.2f}  {r['sessions']:>3} {phases}")
    if len(rows) > limit:
        rest = sum(r["cost"] for r in rows[limit:])
        out.append(f"{'…и ещё ' + str(len(rows) - limit):<{width}}  {'':>8} {'':>8} "
                   f"{'':>9} {rest:>8.2f}")
    out.append("─" * len(head))
    out.append(f"{'ИТОГО':<{width}}  {human(totals['output']):>8} "
               f"{human(totals['cache_write']):>8} {human(totals['cache_read']):>9} "
               f"{totals['cost']:>8.2f}")
    return "\n".join(out)


# ─── HTML ──────────────────────────────────────────────────────────────────────

SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300",
                "#4a3aa7", "#e34948"]
SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300",
               "#9085e9", "#e66767"]


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def daily_chart(records, models):
    """Столбцы по дням, стек по моделям. Дискретные суточные корзины → бары, не линия."""
    by_day = defaultdict(lambda: defaultdict(float))
    for r in records:
        by_day[r["day"]][r["model"]] += r["cost"]
    days = sorted(d for d in by_day if d != "?")
    if not days:
        return "<p class='empty'>Нет данных за период.</p>"

    W, H, PAD_L, PAD_B, PAD_T = 940, 260, 46, 34, 12
    plot_w, plot_h = W - PAD_L - 8, H - PAD_B - PAD_T
    peak = max(sum(by_day[d].values()) for d in days) or 1
    step = plot_w / len(days)
    bar_w = min(28, max(3, step * 0.7))

    ticks = []
    for i in range(4):
        value = peak * i / 3
        y = PAD_T + plot_h - plot_h * i / 3
        ticks.append(f'<line class="grid" x1="{PAD_L}" y1="{y:.1f}" x2="{W - 8}" y2="{y:.1f}"/>'
                     f'<text class="tick" x="{PAD_L - 8}" y="{y + 4:.1f}" '
                     f'text-anchor="end">${value:.0f}</text>')

    bars = []
    for i, day in enumerate(days):
        x = PAD_L + step * i + (step - bar_w) / 2
        cursor = PAD_T + plot_h
        for slot, model in enumerate(models):
            value = by_day[day].get(model, 0)
            if value <= 0:
                continue
            h = max(1.0, plot_h * value / peak)
            cursor -= h
            bars.append(
                f'<rect class="bar s{slot}" x="{x:.1f}" y="{cursor:.1f}" '
                f'width="{bar_w:.1f}" height="{max(0.5, h - 2):.1f}" rx="2" '
                f'data-tip="{esc(day)} · {esc(model)} · ${value:.2f}"/>')
    labels = []
    every = max(1, len(days) // 12)
    for i, day in enumerate(days):
        if i % every == 0:
            labels.append(f'<text class="tick" x="{PAD_L + step * i + step / 2:.1f}" '
                          f'y="{H - PAD_B + 18}" text-anchor="middle">{day[5:]}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Расход по дням">'
            + "".join(ticks) + "".join(bars)
            + f'<line class="axis" x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{W - 8}" '
              f'y2="{PAD_T + plot_h}"/>' + "".join(labels) + "</svg>")


def ranked_bars(rows, limit=8):
    rows = sorted(rows, key=lambda r: -r["cost"])[:limit]
    if not rows:
        return "<p class='empty'>Нет данных.</p>"
    peak = rows[0]["cost"] or 1
    row_h, W = 30, 940
    H = row_h * len(rows) + 8
    parts = []
    for i, r in enumerate(rows):
        y = i * row_h + 4
        w = max(2, 560 * r["cost"] / peak)
        parts.append(
            f'<text class="rowlabel" x="0" y="{y + 16}">{esc(str(r["name"])[:28])}</text>'
            f'<rect class="bar s0" x="180" y="{y + 5}" width="{w:.1f}" height="14" rx="2" '
            f'data-tip="{esc(r["name"])} · ${r["cost"]:.2f} · {human(r["output"])} out"/>'
            f'<text class="rowvalue" x="{180 + w + 10:.1f}" y="{y + 16}">'
            f'${r["cost"]:.2f}</text>')
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Разбивка">'
            + "".join(parts) + "</svg>")


def render_html(records, since, until):
    models = [r["name"] for r in sorted(aggregate(records, "model"),
                                        key=lambda r: -r["cost"]) if r["cost"] > 0][:8]
    totals = {m: sum(r[m] for r in records) for m in METRICS}
    tasks = sorted(aggregate(records, "task"), key=lambda r: -r["cost"])
    model_rows = sorted(aggregate(records, "model"), key=lambda r: -r["cost"])

    legend = "".join(
        f'<span class="legend-item"><i class="sw s{i}"></i>{esc(m)}'
        f'<b>${next(r["cost"] for r in model_rows if r["name"] == m):.2f}</b></span>'
        for i, m in enumerate(models))

    tiles = [("Стоимость", f"${totals['cost']:,.2f}"),
             ("Output", human(totals["output"])),
             ("Cache write", human(totals["cache_write"])),
             ("Cache read", human(totals["cache_read"])),
             ("Задач", str(len([t for t in tasks if t["name"] != NO_TASK])))]
    tiles_html = "".join(
        f'<div class="tile"><span class="tile-label">{esc(label)}</span>'
        f'<span class="tile-value">{esc(value)}</span></div>' for label, value in tiles)

    def table(rows, header, limit=40, with_phases=True):
        def cells(r):
            out = (f'<td class="name" title="{esc(r["name"])}">{esc(r["name"])}</td>'
                   f'<td>{human(r["output"])}</td><td>{human(r["cache_write"])}</td>'
                   f'<td>{human(r["cache_read"])}</td><td>${r["cost"]:.2f}</td>'
                   f'<td>{r["sessions"]}</td>')
            if with_phases:
                phases = " ".join(f"{p} {pct}%" for p, pct in r["phases"] if pct >= 5)
                out += f'<td class="muted">{esc(phases)}</td>'
            return out

        body = "".join(f"<tr>{cells(r)}</tr>"
                       for r in sorted(rows, key=lambda r: -r["cost"])[:limit])
        head = (f'<th>{esc(header)}</th><th>Output</th><th>Cache&nbsp;W</th>'
                f'<th>Cache&nbsp;R</th><th>$</th><th>Сессий</th>'
                + ('<th class="left">Фазы</th>' if with_phases else ""))
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    period = f"{since or records and min(r['day'] for r in records) or '?'} — " \
             f"{until or (max(r['day'] for r in records) if records else '?')}"

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DevFlow · расход токенов</title>
<style>
:root {{
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,.10);
  {"".join(f"--s{i}: {c}; " for i, c in enumerate(SERIES_LIGHT))}
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #fff; --ink-2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,.10);
    {"".join(f"--s{i}: {c}; " for i, c in enumerate(SERIES_DARK))}
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #fff; --ink-2: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,.10);
  {"".join(f"--s{i}: {c}; " for i, c in enumerate(SERIES_DARK))}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
.wrap {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 64px; }}
h1 {{ font-size: 22px; margin: 0 0 4px; }}
.period {{ color: var(--ink-2); margin: 0 0 28px; font-size: 14px; }}
.tiles {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  margin-bottom: 28px; }}
.tile {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 14px 16px; display: flex; flex-direction: column; gap: 4px; }}
.tile-label {{ color: var(--muted); font-size: 12px; text-transform: uppercase;
  letter-spacing: .04em; }}
.tile-value {{ font-size: 24px; font-weight: 600; }}
section {{ background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 18px 20px 20px; margin-bottom: 20px; }}
h2 {{ font-size: 15px; margin: 0 0 14px; font-weight: 600; }}
svg {{ width: 100%; height: auto; display: block; overflow: visible; }}
.grid {{ stroke: var(--grid); stroke-width: 1; }}
.axis {{ stroke: var(--axis); stroke-width: 1; }}
.tick, .rowlabel, .rowvalue {{ fill: var(--muted); font-size: 11px;
  font-variant-numeric: tabular-nums; }}
.rowlabel, .rowvalue {{ fill: var(--ink-2); font-size: 12px; }}
.bar {{ transition: opacity .12s; }}
svg:hover .bar {{ opacity: .5; }}
svg .bar:hover {{ opacity: 1; }}
{"".join(f".s{i} {{ fill: var(--s{i}); }} " for i in range(8))}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 14px;
  font-size: 13px; color: var(--ink-2); }}
.legend-item {{ display: inline-flex; align-items: center; gap: 7px; }}
.legend-item b {{ font-variant-numeric: tabular-nums; }}
.sw {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}
{"".join(f".sw.s{i} {{ background: var(--s{i}); }} " for i in range(8))}
.scroll {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px;
  font-variant-numeric: tabular-nums; }}
th {{ text-align: right; color: var(--muted); font-weight: 500; font-size: 12px;
  padding: 0 0 8px 14px; white-space: nowrap; }}
th:first-child, td:first-child {{ text-align: left; padding-left: 0; }}
td.name {{ max-width: 30ch; overflow: hidden; text-overflow: ellipsis; }}
th.left {{ text-align: left; }}
td {{ text-align: right; padding: 7px 0 7px 14px; border-top: 1px solid var(--grid);
  white-space: nowrap; }}
td.muted {{ color: var(--muted); font-size: 12px; text-align: left; }}
.empty {{ color: var(--muted); }}
#tip {{ position: fixed; pointer-events: none; opacity: 0; transition: opacity .1s;
  background: var(--ink); color: var(--page); padding: 5px 9px; border-radius: 6px;
  font-size: 12.5px; white-space: nowrap; z-index: 10; }}
</style></head><body>
<div class="wrap">
<h1>Расход токенов</h1>
<p class="period">{esc(period)} · {len(records):,} ответов ассистента</p>
<div class="tiles">{tiles_html}</div>

<section><h2>Стоимость по дням, стек по моделям</h2>
{daily_chart(records, models)}
<div class="legend">{legend}</div></section>

<section><h2>Топ задач по стоимости</h2>
{ranked_bars(tasks)}</section>

<section><h2>Задачи</h2><div class="scroll">{table(tasks, "Задача")}</div></section>

<section><h2>Проекты</h2><div class="scroll">{table(aggregate(records, "project"), "Проект")}</div></section>

<section><h2>Фазы</h2><div class="scroll">{table(aggregate(records, "phase"), "Фаза", with_phases=False)}</div></section>

<section><h2>Модели</h2><div class="scroll">{table(model_rows, "Модель")}</div></section>
</div>
<div id="tip"></div>
<script>
const tip = document.getElementById('tip');
document.addEventListener('mouseover', e => {{
  const t = e.target.dataset && e.target.dataset.tip;
  if (!t) return;
  tip.textContent = t; tip.style.opacity = 1;
}});
document.addEventListener('mousemove', e => {{
  if (tip.style.opacity != 1) return;
  const w = tip.offsetWidth;
  tip.style.left = Math.min(e.clientX + 14, innerWidth - w - 8) + 'px';
  tip.style.top = (e.clientY - 34) + 'px';
}});
document.addEventListener('mouseout', e => {{
  if (e.target.dataset && e.target.dataset.tip) tip.style.opacity = 0;
}});
</script></body></html>"""


# ─── CLI ───────────────────────────────────────────────────────────────────────

def tag(task, session):
    session = session or os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not session:
        sys.exit("Нет id сессии: передай --session или запусти внутри Claude Code.")
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "session": session, "task": task.upper()}
    with LEDGER.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"→ {LEDGER}: {task.upper()} ← сессия {session[:8]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--by", default="task",
                    choices=["task", "project", "phase", "model", "day", "session"])
    ap.add_argument("--task")
    ap.add_argument("--project")
    ap.add_argument("--model")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--html", metavar="PATH")
    ap.add_argument("--key-prefixes", default="DEV|SE|DF")
    ap.add_argument("--root", default=str(PROJECTS_ROOT))
    ap.add_argument("--tag", metavar="TASK", help="привязать текущую сессию к задаче")
    ap.add_argument("--session")
    args = ap.parse_args()

    if args.tag:
        return tag(args.tag, args.session)

    key_re = re.compile(rf"\b(?:{args.key_prefixes})-\d{{1,5}}\b", re.I)
    records = scan(Path(args.root), key_re, load_ledger())

    def keep(r):
        return (not args.since or r["day"] >= args.since) \
            and (not args.until or r["day"] <= args.until) \
            and (not args.task or r["task"].upper() == args.task.upper()) \
            and (not args.project or args.project.lower() in r["project"].lower()) \
            and (not args.model or args.model in r["model"])

    records = [r for r in records if keep(r)]
    if not records:
        sys.exit("Нет данных под фильтры.")

    if args.html:
        Path(args.html).write_text(render_html(records, args.since, args.until),
                                   encoding="utf-8")
        print(f"→ {args.html}")
        return

    rows = aggregate(records, args.by)
    totals = {m: sum(r[m] for r in records) for m in METRICS}
    if args.json:
        json.dump({"by": args.by, "totals": totals, "rows": rows},
                  sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        print(render_text(rows, args.by, args.limit, totals))


if __name__ == "__main__":
    main()
