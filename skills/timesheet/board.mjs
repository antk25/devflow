import { html, render, useState, useEffect, useRef } from './vendor/preact-htm.mjs';

const HOURGLASS = html`<svg class="ico" width="10" height="12" viewBox="0 0 10 12" aria-hidden="true">
  <path d="M0 0h10v1.5H9v1.8L6.2 6 9 8.7v1.8h1V12H0v-1.5h1V8.7L3.8 6 1 3.3V1.5H0z" fill="#000"/>
  <path d="M2.2 1.5h5.6v1.3L5 5.4 2.2 2.8zM2.2 10.5 5 7.8l2.8 2.7z" fill="#e0b000"/></svg>`;
const GROUPS = [
  ['wait', 'Ждут решения', HOURGLASS],
  ['work', 'В работе', '▶︎'],
  ['done', 'Готово за 7 дней', '✔︎'],
  ['folded', 'Без движения больше 14 дней', '○'],
];
const LINKS = [['tz', 'ТЗ'], ['research', 'Research'], ['plan', 'План']];
const PALETTE = ['#1084d0', '#c47a00', '#20a060', '#a050d0', '#d04848'];
const OTHER = 'прочее', NO_TASK = '(без задачи)';
const HATCH = 'repeating-linear-gradient(45deg,#666 0 1.5px,#fff 1.5px 4px)';
const WEEKDAYS = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'];

const pad = n => String(n).padStart(2, '0');
const stamp = iso => {
  if (!iso) return '';
  const t = new Date(iso);
  return `${pad(t.getDate())}.${pad(t.getMonth() + 1)} ${pad(t.getHours())}:${pad(t.getMinutes())}`;
};
const ago = (iso, now) => {
  const min = Math.max(0, Math.round((now - new Date(iso)) / 60000));
  return min < 1 ? 'только что' : min < 60 ? `${min} мин назад` : min < 1440 ? `${Math.floor(min / 60)} ч назад` : `${Math.floor(min / 1440)} д назад`;
};
const until = (epoch, now) => {
  const min = Math.max(0, Math.round((epoch * 1000 - now) / 60000));
  return min < 60 ? `${min} мин` : min < 1440 ? `${Math.floor(min / 60)} ч ${pad(min % 60)} мин` : `${Math.floor(min / 1440)} д ${Math.floor(min % 1440 / 60)} ч`;
};
const dur = sec => sec < 60 ? '<1м' : sec < 3600 ? `${Math.round(sec / 60)}м` : `${Math.floor(sec / 3600)}ч ${pad(Math.round(sec % 3600 / 60))}м`;
const usd = c => `$${c.toFixed(2)}`;
const usdShort = c => !c ? '$0' : c >= 100 ? `$${Math.round(c)}` : c >= 10 ? `$${trim(c.toFixed(1))}` : `$${c.toFixed(2)}`;
const trim = s => s.replace(/\.0+$/, '');
const tok = n => n < 1e3 ? String(Math.round(n)) : n < 1e6 ? `${Math.round(n / 1e3)}K` : n < 1e9 ? `${trim((n / 1e6).toFixed(1))}M` : `${trim((n / 1e9).toFixed(2))}B`;
const JIRA = [[/done|released|closed|archived|resolved|готово/i, 'j-done'], [/progress|review|test|работ/i, 'j-prog']];
const jiraClass = s => (JIRA.find(([re]) => re.test(s)) || [null, ''])[1];
const obsidian = path => `obsidian://open?path=${encodeURIComponent(path)}`;
const dayLabel = day => {
  const d = new Date(day + 'T00:00:00Z');
  return `${WEEKDAYS[d.getUTCDay()]}, ${day.slice(8)}.${day.slice(5, 7)}`;
};
const weekend = day => [0, 6].includes(new Date(day + 'T00:00:00Z').getUTCDay());
const color = (name, i) => name === NO_TASK ? null : name === OTHER ? '#a0a0a0' : PALETTE[i % PALETTE.length];
const swatch = (name, i) => name === NO_TASK ? HATCH : color(name, i);

const id = t => t.project + '/' + t.slug;
const title = t => {
  const bare = t.key ? t.title.replace(new RegExp(`^${t.key}\\s*[—–:-]?\\s*`), '') : t.title;
  return bare && bare !== t.key ? bare : null;
};
const stageParts = t => {
  const m = t.stage.label.replace(/^⏸\s*/, '').match(/^(.*?)(?:\s*·\s*(\d+)\s*д)?$/);
  return { text: m[1], age: m[2] == null ? null : Number(m[2]) };
};
const ICON = Object.fromEntries(GROUPS.map(([g, , icon]) => [g, icon]));

const COLUMNS = [
  { id: 'tw', label: '', width: '24px' },
  { id: 'key', label: 'Ключ', width: '82px', sort: t => t.key || '' },
  { id: 'project', label: 'Проект', width: '78px', sort: t => t.project },
  { id: 'title', label: 'Задача', sort: t => title(t) || '' },
  { id: 'stage', label: 'Стадия', width: '172px', sort: t => stageParts(t).age ?? -1, desc: true },
  { id: 'jira', label: 'Jira', width: '86px', sort: t => t.jira?.status || '' },
  { id: 'pr', label: 'PR', width: '112px', sort: t => (t.prs || []).length, desc: true },
  { id: 'time', label: 'Время', width: '66px', r: true, sort: t => t.time?.total || 0, desc: true },
  { id: 'cost', label: '$', width: '118px', r: true, sort: t => t.tokens?.cost || 0, desc: true },
  { id: 'tokens', label: 'Токены', width: '62px', r: true, sort: t => t.tokens?.tokens || 0, desc: true },
];

const store = {
  get: k => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* недоступно */ } },
};

async function api(path, method = 'GET') {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' } });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

const niceMax = v => {
  if (v <= 0) return 1;
  const e = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map(m => m * e).find(m => m >= v);
};

function Chart({ chart, field, fmt, name }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const { days, series } = chart;
  const totals = days.map((_, d) => series.reduce((a, s) => a + (s[field]?.[d] || 0), 0));
  const top = niceMax(Math.max(...totals));
  const H = 170, L = 48, B = 20, T = 16, R = 4;
  const plotW = Math.max(0, width - 12 - L - R), plotH = H - B - T;
  const col = plotW / days.length, bar = Math.min(30, col * 0.64);
  const y = v => T + plotH - v / top * plotH;
  const peak = totals.indexOf(Math.max(...totals));
  const hatch = `hatch-${field}`;

  const columns = width ? days.map((day, d) => {
    const x = L + d * col;
    let acc = 0;
    const parts = series.map((s, i) => {
      const v = s[field]?.[d] || 0;
      if (!v) return null;
      const y1 = y(acc + v), h = y(acc) - y1;
      acc += v;
      return html`<rect x=${x + (col - bar) / 2} y=${y1} width=${bar} height=${Math.max(0, h - (h > 2 ? 1 : 0))}
        fill=${color(s.name, i) || `url(#${hatch})`} />`;
    });
    const label = d === 0 || day.slice(8) === '01' ? `${day.slice(8)}.${day.slice(5, 7)}` : String(Number(day.slice(8)));
    return html`<g key=${day}>
      ${weekend(day) && html`<rect x=${x} y=${T} width=${col} height=${plotH} fill="var(--weekend)" />`}
      ${parts}
      ${d === peak && totals[d] > 0 && html`<text x=${x + col / 2} y=${y(totals[d]) - 4} text-anchor="middle">${fmt(totals[d])}</text>`}
      <text x=${x + col / 2} y=${H - 5} text-anchor="middle" class=${d === days.length - 1 ? 'today' : ''}>${label}</text>
      <rect class=${'hit' + (hover === d ? ' on' : '')} x=${x} y=${T} width=${col} height=${plotH + B} tabindex="0"
        aria-label=${`${dayLabel(day)}: ${fmt(totals[d])}`}
        onMouseEnter=${() => setHover(d)} onMouseLeave=${() => setHover(null)}
        onFocus=${() => setHover(d)} onBlur=${() => setHover(null)} />
    </g>`;
  }) : null;

  const grid = width ? [0, top / 2, top].map(v => html`<g key=${v}>
    <line x1=${L} x2=${width - 12 - R} y1=${y(v)} y2=${y(v)} stroke=${v ? 'var(--grid)' : 'var(--shadow)'} stroke-dasharray=${v ? '2 2' : ''} />
    <text x=${L - 6} y=${y(v) + 4} text-anchor="end">${fmt(v)}</text></g>`) : null;

  let tip = null;
  if (hover != null && width) {
    const rows = series.map((s, i) => ({ s, i, v: s[field]?.[hover] || 0 })).filter(r => r.v > 0).sort((a, b) => b.v - a.v);
    const x = L + hover * col + col / 2 + 6;
    const right = x > width * 0.6;
    tip = html`<div class="tip" style=${right ? `right:${width - x + col + 6}px;top:8px` : `left:${x + col / 2}px;top:8px`}>
      <b>${dayLabel(chart.days[hover])}</b>
      <table>${rows.map(r => html`<tr><td><i class="sw" style=${`display:inline-block;width:9px;height:9px;margin-right:5px;border:1px solid #000;background:${swatch(r.s.name, r.i)}`}></i>${r.s.name}</td><td class="num">${fmt(r.v)}</td></tr>`)}
        <tr class="total"><td>Всего</td><td class="num">${fmt(totals[hover])}</td></tr></table>
    </div>`;
  }

  return html`<fieldset><legend>${name}</legend>
    <div class="plot" ref=${ref}>
      <svg height=${H} role="img" aria-label=${name}>
        <defs><pattern id=${hatch} width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="4" height="4" fill="#fff" /><rect width="1.5" height="4" fill="#666" /></pattern></defs>
        ${grid}${columns}
      </svg>
      ${tip}
    </div>
  </fieldset>`;
}

function Charts({ chart }) {
  if (!chart?.days?.length) return null;
  return html`
    <div class="charts">
      <${Chart} chart=${chart} field="values" fmt=${usdShort} name="Расход $ по дням, 14 дней (UTC)" />
      <${Chart} chart=${chart} field="tokens" fmt=${tok} name="Токены по дням, 14 дней (UTC)" />
    </div>
    <div class="legend">${chart.series.map((s, i) => html`<span><i style=${`background:${swatch(s.name, i)}`}></i>${s.name}</span>`)}</div>`;
}

function Panels({ data, counts, jump, now }) {
  const f = data.facts;
  const trend = f && f.prev_week ? Math.round((f.week - f.prev_week) / f.prev_week * 100) : null;
  return html`<div class="panels">
    ${f && html`<fieldset><legend>Расход за 7 дней</legend>
      <div class="big num">${usd(f.week)}</div>
      ${trend != null && html`<div>${trend > 0 ? '▲' : '▼'} ${Math.abs(trend)}% к прошлой неделе <span class="muted num">(${usd(f.prev_week)})</span></div>`}
      <div class="kv">
        <span class="muted">Токены</span><span class="num">${tok(f.week_tokens || 0)}</span>
        <span class="muted">Без задачи</span><span class="num">${f.no_task_pct}%</span>
      </div>
    </fieldset>`}
    <fieldset><legend>Лимиты Claude</legend>
      ${data.limits?.length ? data.limits.map(l => html`<div class="limit" title=${`${l.used}% окна ${l.label}`}>
          <span>${l.label}</span>
          <div class=${'progress' + (l.used >= 90 ? ' hot' : '')}><i style=${`width:${Math.min(100, l.used)}%`}></i></div>
          <b class="num" style="text-align:right">${l.used}%</b>
          ${l.resets_at && html`<small class="muted">сброс через ${until(l.resets_at, now)}</small>`}
        </div>`)
        : html`<div class="muted">нет свежих данных — их пишет статусная строка Claude Code</div>`}
    </fieldset>
    <fieldset><legend>Задачи</legend>
      <div class="counts">${GROUPS.map(([g, label, icon]) => html`
        <button onClick=${() => jump(g)} title="Показать группу">
          <span>${icon}</span><b class="num">${counts[g]}</b><span>${label.toLowerCase()}</span></button>`)}
      </div>
    </fieldset>
  </div>`;
}

function Days({ days, values, fmt }) {
  const max = Math.max(...days.map(d => values[d] || 0), 0);
  if (!max) return html`<div class="muted">за 14 дней нет</div>`;
  return html`<div class="spark">${days.map(d => {
      const v = values[d] || 0;
      return html`<i class=${v ? '' : 'zero'} style=${`height:${v ? Math.max(2, v / max * 100) : 0}%`} title=${`${dayLabel(d)}: ${v ? fmt(v) : '—'}`}></i>`;
    })}</div>
    <div class="spark-days"><span>${dayLabel(days[0])}</span><span>макс. ${fmt(max)}</span><span>${dayLabel(days[days.length - 1])}</span></div>`;
}

function PrCell({ t }) {
  const prs = t.prs || [];
  if (!prs.length) return '';
  const open = prs.filter(p => p.state === 'open');
  const merged = prs.filter(p => p.state === 'merged');
  const stop = e => e.stopPropagation();
  return html`${open.map(p => html`<a class="pr-open" href=${p.url} target="_blank" onClick=${stop} title=${p.title}>● #${p.number}</a> `)}
    ${merged.length ? html`<span class="pr-merged" title=${merged.map(p => '#' + p.number).join(', ')}>
      ${open.length ? '+' : '✔︎ '}${merged.length === 1 && !open.length ? `#${merged[0].number} слит` : `${merged.length} слито`}</span>` : ''}`;
}

function Row({ t, open, toggle, days, maxCost }) {
  const st = stageParts(t);
  const name = title(t);
  const age = st.age == null ? '' : st.age >= 7 ? 'bad' : st.age >= 3 ? 'warn' : '';
  const stop = e => e.stopPropagation();
  const onKey = e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const rows = [...document.querySelectorAll('tr.row')];
      rows[rows.indexOf(e.currentTarget) + (e.key === 'ArrowDown' ? 1 : -1)]?.focus();
    }
  };
  const cost = t.tokens && !t.tokens.shared ? t.tokens.cost : null;
  const links = LINKS.filter(([k]) => t.links?.[k]);
  return html`
    <tr class=${'row' + (open ? ' sel' : '') + (t.folded ? ' old' : '')} tabindex="0" onClick=${toggle} onKeyDown=${onKey} aria-expanded=${open}>
      <td><span class="tw">${open ? '−' : '+'}</span></td>
      <td class="num"><b>${t.key || html`<span class="muted">—</span>`}</b></td>
      <td>${t.project === '—' ? html`<span class="muted">—</span>` : t.project}</td>
      <td title=${t.title}>${name || html`<span class="muted">задачи нет в vault</span>`}</td>
      <td><span class="st"><span aria-hidden="true">${ICON[t.stage.group] || ''}</span>${st.text}
        ${st.age != null && html`<span class=${'age ' + age} title="столько дней висит">${st.age} д</span>`}</span></td>
      <td>${t.jira ? html`<a class=${'jira ' + jiraClass(t.jira.status)} href=${t.jira.url} target="_blank" onClick=${stop} title=${`${t.jira.summary} — открыть в Jira`}>${t.jira.status}</a>` : ''}</td>
      <td><${PrCell} t=${t} /></td>
      <td class="r num">${!t.time ? '' : t.time.shared ? html`<span class="muted" title="время у другой строки этого ключа">↑</span>` : dur(t.time.total)}</td>
      <td class="r num">${!t.tokens ? '' : t.tokens.shared ? html`<span class="muted" title="расход у другой строки этого ключа">↑</span>`
        : html`<div class="bar" style=${`--w:${maxCost ? Math.round(cost / maxCost * 100) : 0}%`} title="доля от самой дорогой задачи в списке"><i></i><span>${usd(cost)}</span></div>`}</td>
      <td class="r num">${t.tokens && !t.tokens.shared ? tok(t.tokens.tokens) : ''}</td>
    </tr>
    ${open && html`<tr class="detail"><td colSpan=${COLUMNS.length}><div class="dgrid">
      <div>
        <h4>Задача</h4>
        <div>${t.title}</div>
        <div class="muted num">${t.slug}${t.stage.since ? ` · стадия с ${stamp(t.stage.since)}` : ''}</div>
        <div class="links" style="margin-top:6px">
          ${links.map(([k, label]) => html`<a class="btn" href=${obsidian(t.links[k])}>${label}</a>`)}
          ${t.jira && html`<a class="btn" href=${t.jira.url} target="_blank">${t.key} в Jira ↗</a>`}
          ${!links.length && !t.jira ? html`<span class="muted">артефактов нет</span>` : null}
        </div>
      </div>
      <div>
        <h4>Pull requests</h4>
        ${(t.prs || []).length ? (t.prs || []).map(p => html`<div><a class=${'pr-' + p.state} href=${p.url} target="_blank">#${p.number} ${p.state}</a>
          <span class="muted">${p.repo}</span> — ${p.title}</div>`) : html`<span class="muted">нет</span>`}
      </div>
      <div>
        <h4>Время по дням</h4>
        ${t.time?.shared ? html`<span class="muted">у другой строки этого ключа ↑</span>` : html`<${Days} days=${days} values=${t.time?.days || {}} fmt=${dur} />`}
      </div>
      <div>
        <h4>$ по дням</h4>
        ${t.tokens?.shared ? html`<span class="muted">у другой строки этого ключа ↑</span>` : html`<${Days} days=${days} values=${t.tokens?.days || {}} fmt=${usd} />`}
      </div>
    </div></td></tr>`}`;
}

function App() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [query, setQuery] = useState('');
  const [project, setProject] = useState('');
  const [collapsed, setCollapsed] = useState(new Set(['folded']));
  const [sort, setSort] = useState(null);
  const [now, setNow] = useState(Date.now());
  const [charts, setCharts] = useState(store.get('board.charts') !== '0');
  const search = useRef(null);

  const load = async (refresh = false) => {
    const started = Date.now();
    setBusy({ started, refresh });
    try {
      setData(await api(refresh ? '/api/board/refresh' : '/api/board', refresh ? 'POST' : 'GET'));
      setError(null);
      if (refresh) store.set('board.refreshMs', String(Date.now() - started));
    } catch (e) { setError(e.message); }
    setBusy(null);
  };
  useEffect(() => {
    load();
    const onVisible = () => { if (document.visibilityState === 'visible') load(); };
    const onKey = e => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') { e.preventDefault(); search.current?.focus(); }
    };
    document.addEventListener('visibilitychange', onVisible);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('visibilitychange', onVisible); document.removeEventListener('keydown', onKey); };
  }, []);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), busy ? 500 : 30000);
    return () => clearInterval(timer);
  }, [busy]);

  const all = [...(data?.tasks || []), ...(data?.folded || []).map(t => ({ ...t, folded: true }))];
  const projects = [...new Set(all.map(t => t.project))].sort();
  const q = query.trim().toLowerCase();
  const visible = all.filter(t => (!project || t.project === project)
    && (!q || [t.key, t.title, t.project, t.slug, t.jira?.status].join(' ').toLowerCase().includes(q)));
  const groupOf = t => t.folded ? 'folded' : t.stage.group;
  const counts = Object.fromEntries(GROUPS.map(([g]) => [g, visible.filter(t => groupOf(t) === g).length]));
  const maxCost = Math.max(0, ...visible.map(t => (t.tokens && !t.tokens.shared ? t.tokens.cost : 0)));
  const days = data?.chart?.days || [];

  const toggleGroup = g => setCollapsed(c => { const n = new Set(c); n.has(g) ? n.delete(g) : n.add(g); return n; });
  const jump = g => {
    setCollapsed(c => { const n = new Set(c); n.delete(g); return n; });
    requestAnimationFrame(() => document.getElementById('g-' + g)?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };
  const sortBy = c => setSort(s => !s || s.id !== c.id ? { id: c.id, desc: !!c.desc }
    : s.desc === !!c.desc ? { id: c.id, desc: !s.desc } : null);
  const sorted = list => {
    if (!sort) return list;
    const c = COLUMNS.find(x => x.id === sort.id);
    return [...list].sort((a, b) => {
      const va = c.sort(a), vb = c.sort(b);
      const r = typeof va === 'number' ? va - vb : String(va).localeCompare(String(vb), 'ru');
      return sort.desc ? -r : r;
    });
  };

  const rows = [];
  for (const [g, label, icon] of GROUPS) {
    const list = visible.filter(t => groupOf(t) === g);
    if (!list.length) continue;
    const shut = collapsed.has(g) && !q;
    rows.push(html`<tr class="group" id=${'g-' + g} key=${'g' + g} onClick=${() => toggleGroup(g)}>
      <td colSpan=${COLUMNS.length}><span class="tw">${shut ? '+' : '−'}</span> ${icon} ${label} <span class="muted">(${list.length})</span></td></tr>`);
    if (shut) continue;
    for (const t of sorted(list)) {
      rows.push(html`<${Row} key=${id(t)} t=${t} open=${open === id(t)} days=${days} maxCost=${maxCost}
        toggle=${() => setOpen(open === id(t) ? null : id(t))} />`);
    }
  }

  const expected = Number(store.get('board.refreshMs')) || 0;
  const elapsed = busy ? now - busy.started : 0;
  const sources = [['PR', data?.prs_error], ['Jira', data?.jira_error], ['Время', data?.time_error], ['Токены', data?.tokens_error]];

  return html`<div class="window">
    <div class="title-bar">
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="1" y="2" width="14" height="12" fill="#c0c0c0" stroke="#000"/>
        <rect x="1" y="2" width="14" height="3" fill="#000080"/><rect x="3" y="7" width="3" height="5" fill="#1084d0"/>
        <rect x="7" y="9" width="3" height="3" fill="#c47a00"/><rect x="11" y="6" width="2" height="6" fill="#20a060"/></svg>
      <span>DevFlow — доска задач</span><span class="grow"></span>
      ${data && html`<span class="stamp">снимок ${stamp(data.generated)}</span>`}
    </div>
    <div class="toolbar">
      <button class="btn" disabled=${!!busy} onClick=${() => load(true)} title="Пересчитать снимок: транскрипты, токены, PR, Jira">↻ Обновить</button>
      <button class=${'btn' + (charts ? ' on' : '')} aria-pressed=${charts} title="Показать или скрыть сводку и графики"
        onClick=${() => { store.set('board.charts', charts ? '0' : '1'); setCharts(!charts); }}>▥ Сводка</button>
      <a class="btn" href="/">▦ Табель</a>
      <span class="sep"></span>
      <label class="fld">Найти:
        <input class="input" ref=${search} type="search" name="q" value=${query} placeholder="ключ, название, проект — «/»"
          onInput=${e => setQuery(e.target.value)} onKeyDown=${e => { if (e.key === 'Escape') setQuery(''); }} /></label>
      <label class="fld">Проект:
        <select class="input" name="project" value=${project} onChange=${e => setProject(e.target.value)}>
          <option value="">все</option>
          ${projects.map(p => html`<option value=${p}>${p === '—' ? '(без проекта)' : p}</option>`)}
        </select></label>
      ${(q || project) && html`<button class="btn" onClick=${() => { setQuery(''); setProject(''); }}>Сбросить</button>`}
    </div>
    <div class="content">
      ${data && charts && html`<${Panels} data=${data} counts=${counts} jump=${jump} now=${now} />`}
      ${data && charts && html`<${Charts} chart=${data.chart} />`}
      <div class="listview">
        ${data && !rows.length ? html`<div class="empty">${q || project ? 'ничего не найдено' : 'задач нет'}</div>` : html`
        <table class="list">
          <colgroup>${COLUMNS.map(c => html`<col style=${c.width ? `width:${c.width}` : ''} />`)}</colgroup>
          <thead><tr>${COLUMNS.map(c => html`<th class=${(c.sort ? 'sort' : '') + (c.r ? ' r' : '')}
            onClick=${c.sort ? () => sortBy(c) : null} title=${c.sort ? 'Сортировать' : ''}
            aria-sort=${sort?.id === c.id ? (sort.desc ? 'descending' : 'ascending') : null}>
            ${c.label}${sort?.id === c.id ? (sort.desc ? ' ▼' : ' ▲') : ''}</th>`)}</tr></thead>
          <tbody>${rows}</tbody>
        </table>`}
      </div>
    </div>
    <div class="status-bar">
      <div class="main">${busy?.refresh ? html`
          <div class=${'progress' + (expected ? '' : ' marquee')}><i style=${expected ? `width:${Math.min(95, elapsed / expected * 100)}%` : ''}></i></div>
          <span>Пересчёт… ${Math.round(elapsed / 1000)} с${expected ? ` из ~${Math.round(expected / 1000)}` : ''}</span>`
        : error ? html`<span class="src bad">⚠ ${error}</span>` : busy ? 'Загрузка…' : 'Готово'}</div>
      ${data && html`<div title=${stamp(data.generated)}>Снимок ${ago(data.generated, now)}</div>`}
      ${data && html`<div>${q || project ? `Найдено ${visible.length} из ${all.length}` : `Задач: ${all.length}`}</div>`}
      ${data && html`<div>${sources.map(([name, err]) => html`<span class=${'src' + (err ? ' bad' : '')} title=${err || 'в порядке'}>${name} ${err ? '✗' : '✓'}</span>`)}
        ${data.errors?.length ? html`<span class="src bad" title=${data.errors.join('\n')}>⚠ не прочитано: ${data.errors.length}</span>` : null}</div>`}
    </div>
  </div>`;
}

render(html`<${App} />`, document.getElementById('app'));
