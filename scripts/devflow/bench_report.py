"""`devflow bench report <run>`: the matrix task × combo, a summary per combo, every combo against the base, A/A′ noise."""
import statistics
from math import comb
from pathlib import Path

from .policy import PHASES

TOKEN_KEYS = ('input', 'output', 'cache_read', 'cache_write')
RUNNERS = ('claude', 'pi')
JUDGE_KEYS = ('same_requirements', 'no_extra_steps', 'boundaries')


def combo_key(combo, replica):
    return f'{combo} r{replica}' if replica and replica > 1 else combo


def summarize(records):
    """Pairs by their last finished attempt. `rows[(task, key)]` carries outcome, resolved, diff, tokens, cost per runner,
    time, tool calls, phases, steps, open questions; `specs[key]` — runner/model/effort per phase; mismatches and
    skipped combos are kept aside. `mode` is `judge` when the run was scored by `judge` lines (references set) and
    `tests` otherwise."""
    ends = {}
    for r in records:
        if r.get('type') == 'pair_end' and r.get('attempt', 1) >= ends.get(r['pair'], {}).get('attempt', 0):
            ends[r['pair']] = r
    starts = {(r['pair'], r.get('attempt', 1)): r for r in records if r.get('type') == 'pair_start'}
    evals = {(r['pair'], r.get('attempt', 1)): r for r in records if r.get('type') == 'eval'}
    quality = {(r['pair'], r.get('attempt', 1)): r for r in records if r.get('type') == 'quality'}
    judges = {(r['pair'], r.get('attempt', 1)): r for r in records if r.get('type') == 'judge'}
    rows, specs, tasks, keys = {}, {}, [], []
    for pair, end in ends.items():
        attempt = end.get('attempt', 1)
        start = starts.get((pair, attempt), {})
        key = combo_key(start.get('combo'), start.get('replica', 1))
        task = start.get('task') or end.get('task')
        phases = [r for r in records if r.get('type') == 'phase' and r['pair'] == pair and r.get('attempt', 1) == attempt]
        specs.setdefault(key, {p['phase']: f"{p['runner']}:{p['model_req']}:{p['effort_req']}" for p in phases})
        ev = evals.get((pair, attempt))
        q = quality.get((pair, attempt), {})
        j = judges.get((pair, attempt))
        row = {'judge': None if j is None else judge_scores(j),
               'pair': pair, 'task': task, 'combo': key, 'outcome': end.get('outcome'), 'error_text': end.get('error_text'),
               'resolved': None if ev is None else bool(ev.get('resolved')), 'reason': (ev or {}).get('reason'),
               'size_ratio': (ev or {}).get('diff', {}).get('size_ratio'), 'patch_bytes': end.get('patch_bytes'),
               'lint_errors': q.get('lint_errors'), 'new_static_errors': q.get('new_static_errors'),
               'phases': end.get('phases'), 'steps': end.get('steps'), 'open_questions': end.get('open_questions'),
               'duration_s': round(sum(float(p.get('duration_s') or 0) for p in phases), 1),
               'tools': sum(sum((p.get('tools') or {}).values()) for p in phases),
               'cost': {runner: round(sum(float(p.get('cost_usd') or 0) for p in phases if p.get('runner') == runner), 4)
                        for runner in RUNNERS},
               'cost_source': sorted({p['cost_source'] for p in phases if p.get('cost_source')}),
               **{k: sum(int(p.get(k) or 0) for p in phases) for k in TOKEN_KEYS}}
        rows[(task, key)] = row
        tasks.append(task) if task not in tasks else None
        keys.append(key) if key not in keys else None
    skipped = {r['combo']: r['reason'] for r in records if r.get('type') == 'combo_skipped'}
    paused = [r for r in records if r.get('type') == 'run_paused']
    return {'tasks': tasks, 'combos': keys, 'rows': rows, 'specs': specs, 'skipped': skipped, 'paused': paused,
            'mode': 'judge' if judges else 'tests'}


def judge_scores(record):
    """The judge line flattened: plan validity, the lowest Jev coverage `noul` with the flagged count, the three judge
    `noul` values; None where the check gave no number."""
    validate, cover, verdict = record.get('validate') or {}, record.get('coverage') or {}, record.get('judge') or {}
    return {'valid': validate.get('ok'), 'coverage_min': cover.get('min'), 'flagged': cover.get('flagged'),
            **{key: (verdict.get('noul') or {}).get(key) for key in JUDGE_KEYS},
            'reason': record.get('reason') or cover.get('reason') or verdict.get('reason')}


def mcnemar(b, c):
    """Exact two-sided McNemar on the discordant counts: the pairs the base solved alone (`b`) and the combo solved alone (`c`)."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def holm(pvalues):
    """Holm step-down on `{name: p}`; adjusted values, monotone."""
    order = sorted(pvalues, key=pvalues.get)
    adjusted, running, m = {}, 0.0, len(order)
    for i, name in enumerate(order):
        running = max(running, min(1.0, (m - i) * pvalues[name]))
        adjusted[name] = running
    return adjusted


def total_cost(row):
    return sum(row['cost'].values())


def compare(summary, base):
    """Every combo against `base`: McNemar over the tasks both evaluated (Holm across combos), median per-task ratio of cost
    and time with a sign test. None when the base is not in the run."""
    rows = summary['rows']
    if base not in summary['combos']:
        return None
    result = {}
    for key in summary['combos']:
        if key == base:
            continue
        common = [t for t in summary['tasks'] if (t, base) in rows and (t, key) in rows]
        judged = [t for t in common if rows[(t, base)]['resolved'] is not None and rows[(t, key)]['resolved'] is not None]
        b = sum(1 for t in judged if rows[(t, base)]['resolved'] and not rows[(t, key)]['resolved'])
        c = sum(1 for t in judged if rows[(t, key)]['resolved'] and not rows[(t, base)]['resolved'])
        entry = {'tasks': len(judged), 'base_only': b, 'combo_only': c, 'p': round(mcnemar(b, c), 4)}
        for metric, pick in (('cost', total_cost), ('time', lambda r: r['duration_s'])):
            ratios = [pick(rows[(t, key)]) / pick(rows[(t, base)]) for t in common if pick(rows[(t, base)])]
            up, down = sum(1 for x in ratios if x > 1), sum(1 for x in ratios if x < 1)
            entry[metric] = {'median_ratio': round(statistics.median(ratios), 2) if ratios else None,
                             'p': round(mcnemar(up, down), 4) if ratios else None}
        result[key] = entry
    for key, p in holm({k: v['p'] for k, v in result.items()}).items():
        result[key]['p_holm'] = round(p, 4)
    return result


def noise(summary):
    """A/A′ per combo with replicas: tasks where replica 1 and 2 disagree on `resolved`, the relative spread of cost."""
    rows, out = summary['rows'], {}
    for key in summary['combos']:
        if ' r2' not in key:
            continue
        first = key[:-3]
        pairs = [(rows[(t, first)], rows[(t, key)]) for t in summary['tasks'] if (t, first) in rows and (t, key) in rows]
        disagree = [a['task'] for a, b in pairs if a['resolved'] is not None and b['resolved'] is not None and a['resolved'] != b['resolved']]
        spreads = [abs(total_cost(a) - total_cost(b)) / ((total_cost(a) + total_cost(b)) / 2)
                   for a, b in pairs if total_cost(a) + total_cost(b)]
        out[first] = {'tasks': len(pairs), 'disagree': disagree,
                      'cost_spread_median': round(statistics.median(spreads), 2) if spreads else None,
                      'cost_spread_max': round(max(spreads), 2) if spreads else None}
    return out


def per_combo(summary):
    rows = summary['rows']
    out = {}
    for key in summary['combos']:
        group = [r for (_, k), r in rows.items() if k == key and r['outcome'] != 'model_mismatch']
        judged = [r for r in group if r['resolved'] is not None]
        med = lambda pick: round(statistics.median(pick(r) for r in group), 1) if group else None
        out[key] = {'pairs': len(group), 'judged': len(judged), 'resolved': sum(1 for r in judged if r['resolved']),
                    'completed': sum(1 for r in group if r['outcome'] in ('completed', 'planned')),
                    'lint_errors': sum(r['lint_errors'] or 0 for r in group if r['lint_errors'] is not None),
                    'new_static_errors': sum(r['new_static_errors'] for r in group if r['new_static_errors'] is not None),
                    'static_judged': sum(1 for r in group if r['new_static_errors'] is not None),
                    'tokens': {k: {'sum': sum(r[k] for r in group), 'median': med(lambda r, k=k: r[k])} for k in TOKEN_KEYS},
                    'cost': {runner: {'sum': round(sum(r['cost'][runner] for r in group), 4),
                                      'median': round(statistics.median(r['cost'][runner] for r in group), 4) if group else None}
                             for runner in RUNNERS},
                    'time': {'sum': round(sum(r['duration_s'] for r in group), 1), 'median': med(lambda r: r['duration_s'])},
                    'tools': {'sum': sum(r['tools'] for r in group), 'median': med(lambda r: r['tools'])},
                    'phases': med(lambda r: r['phases'] or 0), 'steps': med(lambda r: r['steps'] or 0),
                    'open_questions': med(lambda r: r['open_questions'] or 0)}
        if summary.get('mode') == 'judge':
            scored = [r['judge'] for r in group if r['judge'] is not None and r['judge']['valid'] is not None]
            median = lambda key: (lambda xs: round(statistics.median(xs), 2) if xs else None)([s[key] for s in scored if s[key] is not None])
            out[key]['judge'] = {'scored': len(scored), 'valid': sum(1 for s in scored if s['valid']),
                                 'coverage_min': median('coverage_min'), **{k: median(k) for k in JUDGE_KEYS}}
    return out


def mark(row):
    if row is None:
        return '—'
    if row['outcome'] == 'model_mismatch':
        return '⚠'
    if row['judge'] is not None:
        return {True: '✓', False: '✗', None: '—'}[row['judge']['valid']]
    return {True: '✓', False: '✗', None: '—'}[row['resolved']]


def score(value):
    return '—' if value is None else f'{value:.2f}'


def judged(row):
    """The judge part of a matrix cell: validity, lowest coverage with flags, the three judge scores."""
    j = row['judge']
    if j is None:
        return 'судья —'
    flags = '' if j['flagged'] is None else f" ({j['flagged']}⚑)"
    return f"покрытие {score(j['coverage_min'])}{flags} · судья {'/'.join(score(j[k]) for k in JUDGE_KEYS)}"


def money(row):
    return ' / '.join(f'{runner} ${row["cost"][runner]:.2f}' for runner in RUNNERS if row['cost'][runner])


def static(row):
    if row['lint_errors'] is None:
        return '—'
    new = row['new_static_errors']
    return f"{row['lint_errors']}/{'—' if new is None else f'{new:+d}'}"


def render(name, base, summary, stats, comparison, aa):
    rows, keys = summary['rows'], summary['combos']
    by_judge = summary.get('mode') == 'judge'
    lines = [f'# Бенчмарк {name}', '', f'База: `{base}`' + ('' if comparison is not None else ' — в прогоне отсутствует, сравнения нет'),
             '', '## Связки', '']
    for key in keys:
        spec = summary['specs'].get(key, {})
        lines.append(f'- `{key}`: ' + ', '.join(f'{phase} {spec.get(phase, "—")}' for phase in PHASES))
    for combo, reason in summary['skipped'].items():
        lines.append(f'- `{combo}`: пропущена — {reason}')
    lines += ['', '## Матрица', '', '| задача | ' + ' | '.join(keys) + ' |', '|---|' + '---|' * len(keys)]
    for task in summary['tasks']:
        cells = []
        for key in keys:
            r = rows.get((task, key))
            if r is None:
                cells.append(mark(r))
                continue
            quality = judged(r) if by_judge else f"diff×{r['size_ratio'] if r['size_ratio'] is not None else '—'} · стат {static(r)}"
            cells.append(f"{mark(r)} {r['outcome']} · {quality} · {r['input'] + r['cache_read'] + r['cache_write']}/{r['output']} ток · "
                         f"{money(r) or '$0'} · {r['duration_s']:.0f}с")
        lines.append(f'| {task} | ' + ' | '.join(cells) + ' |')
    if by_judge:
        legend = ('Ячейка: план валиден (✓/✗/— без оценки/⚠ не та модель) · итог пары · покрытие — наименьший noul Jev по требованиям '
                  'research кандидата (⚑ ниже порога) · судья — noul «те же требования / нет лишних шагов / границы архитектуры» '
                  'эталона против кандидата · токены вход+кэш/выход · стоимость по исполнителю · время.')
        first = '| связка | валидно | завершено (planned) | покрытие мед | судья мед (треб/шаги/границы) |'
    else:
        legend = ('Ячейка: решена (✓/✗/— без оценки/⚠ не та модель) · итог пары · diff к эталону · статанализ (ошибок линтера/новых '
                  'ошибок phpstan, — без проверки) · токены вход+кэш/выход · стоимость по исполнителю · время.')
        first = '| связка | решено | завершено | статанализ (линт Σ/новых Σ) |'
    lines += ['', legend, '', '## Сводка по связкам', '',
              first + ' токены вход (Σ/мед) | выход (Σ/мед) | кэш (Σ/мед) | '
              'claude $ (Σ/мед) | pi $ (Σ/мед) | время с (Σ/мед) | инструменты (Σ/мед) | фаз | шагов | откр. вопросов |',
              '|---|' + '---|' * (14 if by_judge else 13)]
    for key in keys:
        s = stats[key]
        t = s['tokens']
        cache = {'sum': t['cache_read']['sum'] + t['cache_write']['sum'],
                 'median': None if t['cache_read']['median'] is None else t['cache_read']['median'] + t['cache_write']['median']}
        fmt = lambda d, p='': f"{d['sum']}{p}/{d['median'] if d['median'] is not None else '—'}{p}"
        if by_judge:
            j = s['judge']
            head = (f"| {key} | {j['valid']}/{j['scored']} | {s['completed']}/{s['pairs']} | {score(j['coverage_min'])} | "
                    f"{'/'.join(score(j[k]) for k in JUDGE_KEYS)} |")
        else:
            static_cell = f"{s['lint_errors']}/{s['new_static_errors']:+d} ({s['static_judged']} пар)" if s['static_judged'] else '—'
            head = f"| {key} | {s['resolved']}/{s['judged']} | {s['completed']}/{s['pairs']} | {static_cell} |"
        lines.append(f"{head} {fmt(t['input'])} | {fmt(t['output'])} | "
                     f"{fmt(cache)} | {fmt(s['cost']['claude'])} | {fmt(s['cost']['pi'])} | {fmt(s['time'])} | {fmt(s['tools'])} | "
                     f"{s['phases']} | {s['steps']} | {s['open_questions']} |")
    if comparison and by_judge:
        lines += ['', f'## Сравнение с базой `{base}`', '', '| связка | стоимость ×мед (p знак.) | время ×мед (p знак.) |', '|---|---|---|']
        for key, c in comparison.items():
            lines.append(f"| {key} | {c['cost']['median_ratio']} ({c['cost']['p']}) | {c['time']['median_ratio']} ({c['time']['p']}) |")
    elif comparison:
        lines += ['', f'## Сравнение с базой `{base}`', '',
                  '| связка | задач | решила только база | только связка | p Мак-Немара | p Холма | стоимость ×мед (p знак.) | время ×мед (p знак.) |',
                  '|---|' + '---|' * 7]
        for key, c in comparison.items():
            lines.append(f"| {key} | {c['tasks']} | {c['base_only']} | {c['combo_only']} | {c['p']} | {c['p_holm']} | "
                         f"{c['cost']['median_ratio']} ({c['cost']['p']}) | {c['time']['median_ratio']} ({c['time']['p']}) |")
        lines += ['', 'Отношение стоимости — по сумме долларов всех исполнителей пары; знаковый тест — на отклонение медианы от 1.']
    lines += ['', '## Шум A/A′', '']
    if aa:
        for combo, n in aa.items():
            lines.append(f"- `{combo}`: {n['tasks']} задач, разошлись по решённости: {len(n['disagree'])}"
                         f"{' (' + ', '.join(n['disagree']) + ')' if n['disagree'] else ''}; разброс стоимости мед {n['cost_spread_median']}, "
                         f"макс {n['cost_spread_max']}")
    else:
        lines.append('Реплик нет — разброс между одинаковыми связками не измерен.')
    mismatched = [r for r in rows.values() if r['outcome'] == 'model_mismatch']
    if mismatched:
        lines += ['', '## Не та модель', ''] + [f"- {r['pair']}: {r['error_text']}" for r in mismatched]
    if summary['paused']:
        lines += ['', '## Паузы', ''] + [f"- {p['at']} {p.get('pair', '')}: {p['reason']}" for p in summary['paused']]
    return '\n'.join(lines) + '\n'


def report(name, records, directory, base='production'):
    summary = summarize(records)
    stats = per_combo(summary)
    comparison = compare(summary, base)
    aa = noise(summary)
    path = Path(directory) / 'report.md'
    path.write_text(render(name, base, summary, stats, comparison, aa), encoding='utf-8')
    return {'run': name, 'report': str(path), 'base': base, 'combos': summary['combos'], 'tasks': len(summary['tasks']),
            'mode': summary['mode'],
            'resolved': {k: f"{s['resolved']}/{s['judged']}" for k, s in stats.items()},
            **({'judge': {k: s['judge'] for k, s in stats.items()}} if summary['mode'] == 'judge' else {}),
            'comparison': comparison, 'noise': aa, 'skipped': summary['skipped']}
