import { html, render, useState, useEffect } from './vendor/preact-htm.mjs';

const GROUPS = { wait: 'ждут решения', work: 'в работе', done: 'готово за 7 дней' };
const LINKS = [['tz', 'ТЗ'], ['research', 'research'], ['plan', 'plan']];

const stamp = iso => {
  if (!iso) return '';
  const t = new Date(iso);
  const pad = n => String(n).padStart(2, '0');
  return `${pad(t.getDate())}.${pad(t.getMonth() + 1)} ${pad(t.getHours())}:${pad(t.getMinutes())}`;
};
const obsidian = path => `obsidian://open?path=${encodeURIComponent(path)}`;
const COLS = 8;
const dur = sec => sec < 60 ? '<1м' : sec < 3600 ? `${Math.round(sec / 60)}м` : `${Math.floor(sec / 3600)}ч ${String(Math.round(sec % 3600 / 60)).padStart(2, '0')}м`;
const time = t => !t.time ? '' : t.time.shared ? html`<span class="muted" title="время у другой строки этого ключа">↑</span>` : dur(t.time.total);
const days = t => Object.entries(t.time?.days || {}).sort((a, b) => b[0].localeCompare(a[0]))
  .map(([d, s]) => html`<span class="day mono">${d.slice(5)} ${dur(s)}</span>`);
const usd = c => `$${c.toFixed(2)}`;
const tok = n => n < 1e3 ? String(n) : n < 1e6 ? `${Math.round(n / 1e3)}K` : `${(n / 1e6).toFixed(1)}M`;
const tokens = t => !t.tokens ? '' : t.tokens.shared ? html`<span class="muted" title="токены у другой строки этого ключа">↑</span>` : `${usd(t.tokens.cost)} · ${tok(t.tokens.tokens)}`;
const tokenDays = t => Object.entries(t.tokens?.days || {}).sort((a, b) => b[0].localeCompare(a[0]))
  .map(([d, c]) => html`<span class="day mono">${d.slice(5)} ${usd(c)}</span>`);
const prs = t => (t.prs || []).map(p => html`<a class="pr" href=${p.url} target="_blank" title=${p.title}>#${p.number} ${p.state}</a>`);

const PALETTE = ['#2F6FB0', '#C98A2B', '#4E9A6B', '#8E5BB5', '#C1554E'];
const color = (name, i) => name === '(без задачи)' ? 'var(--ink-3)' : name === 'прочее' ? 'var(--rule-strong)' : PALETTE[i % PALETTE.length];

function Facts({ facts, limits }) {
  if (!facts) return null;
  return html`<div class="facts">
    <span>7 дн: <b class="mono">${usd(facts.week)}</b></span>
    <span class="muted">·</span><span>неделей раньше <span class="mono">${usd(facts.prev_week)}</span></span>
    <span class="muted">·</span><span>без задачи <span class="mono">${facts.no_task_pct}%</span></span>
    ${limits.map(l => html`<span class="limit" title=${`${l.used}% окна ${l.label}`}>
      <span class="muted">${l.label}</span>
      <span class=${'cells' + (l.used >= 100 ? ' bad' : '')}>${[...Array(10)].map((_, i) =>
        html`<i style=${`--fill:${Math.max(0, Math.min(1, l.cells - i))}`}></i>`)}</span>
      <span class="mono">${l.used}%</span></span>`)}
  </div>`;
}

function Chart({ chart }) {
  if (!chart?.days?.length) return null;
  const W = 14, H = 120, GAP = 3, PAD = 4;
  const totals = chart.days.map((_, d) => chart.series.reduce((a, s) => a + s.values[d], 0));
  const max = Math.max(...totals, 0.01);
  const bars = chart.days.map((day, d) => {
    let y = H;
    const parts = chart.series.map((s, i) => {
      const h = s.values[d] / max * (H - PAD);
      y -= h;
      return html`<rect x=${d * (W + GAP)} y=${y} width=${W} height=${h} fill=${color(s.name, i)}><title>${day.slice(5)} ${s.name}: ${usd(s.values[d])}</title></rect>`;
    });
    return html`<g>${parts}<text x=${d * (W + GAP) + W / 2} y=${H + 11} text-anchor="middle">${day.slice(8)}</text></g>`;
  });
  return html`<div class="chart">
    <svg viewBox=${`0 0 ${chart.days.length * (W + GAP) - GAP} ${H + 14}`} width=${chart.days.length * (W + GAP) - GAP} height=${H + 14}>${bars}</svg>
    <div class="legend">${chart.series.map((s, i) => html`<span><i style=${`background:${color(s.name, i)}`}></i>${s.name}</span>`)}
      <span class="muted">макс. день ${usd(max)}</span></div>
  </div>`;
}

async function api(path, method = 'GET') {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' } });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

function Row({ t, open, toggle }) {
  const links = LINKS.filter(([k]) => t.links[k]);
  return html`
    <tr class=${'row' + (open ? ' open' : '')} onClick=${toggle}>
      <td class="key mono">${t.key || html`<span class="muted">—</span>`}</td>
      <td class="proj">${t.project}</td>
      <td>${t.title}</td>
      <td class="stage"><span class=${'pill ' + t.stage.group}>${t.stage.label}</span></td>
      <td class="jira">${t.jira ? html`<a href=${t.jira.url} target="_blank" title=${t.jira.summary}>${t.jira.status}</a>` : ''}</td>
      <td class="prs">${prs(t)}</td>
      <td class="time mono">${time(t)}</td>
      <td class="tokens mono">${tokens(t)}</td>
    </tr>
    ${open && html`<tr class="detail"><td colSpan=${COLS}>
      <span class="mono muted">${t.slug}</span><br/>
      ${t.jira && html`<a href=${t.jira.url} target="_blank">${t.key} в Jira</a>`}
      ${links.length ? links.map(([k, name]) => html`<a href=${obsidian(t.links[k])}>${name}</a>`)
        : html`<span class="muted">артефактов нет</span>`}
      ${t.time?.days && html`<div class="days">${days(t)}</div>`}
      ${t.tokens?.days && Object.keys(t.tokens.days).length ? html`<div class="days">$ по дням: ${tokenDays(t)}</div>` : null}
    </td></tr>`}`;
}

function App() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(null);
  const [showFolded, setShowFolded] = useState(false);

  const load = async (refresh = false) => {
    setBusy(true);
    try {
      setData(await api(refresh ? '/api/board/refresh' : '/api/board', refresh ? 'POST' : 'GET'));
      setError(null);
    } catch (e) { setError(e.message); }
    setBusy(false);
  };
  useEffect(() => {
    load();
    const onVisible = () => { if (document.visibilityState === 'visible') load(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  const tasks = data?.tasks || [];
  const folded = data?.folded || [];
  const row = t => html`<${Row} key=${t.project + '/' + t.slug} t=${t} open=${open === t.project + '/' + t.slug}
      toggle=${() => setOpen(open === t.project + '/' + t.slug ? null : t.project + '/' + t.slug)} />`;
  const rows = [];
  let group = null;
  for (const t of tasks) {
    if (t.stage.group !== group) {
      group = t.stage.group;
      rows.push(html`<tr class="sep" key=${'g' + group}><td colSpan=${COLS}>${GROUPS[group] || group}</td></tr>`);
    }
    rows.push(row(t));
  }
  if (showFolded && folded.length) {
    rows.push(html`<tr class="sep" key="gfolded"><td colSpan=${COLS}>без движения > 14 дн</td></tr>`);
    folded.forEach(t => rows.push(row(t)));
  }

  return html`
    <header class="top"><div class="top-in">
      <span class="brand"><a href="/">Табель</a> · Задачи</span>
      <span class="grow"></span>
      ${error && html`<span class="stamp" style="color:var(--bad)">${error}</span>`}
      ${data?.prs_error && html`<span class="stamp" style="color:var(--bad)">PR: ${data.prs_error}</span>`}
      ${data?.jira_error && html`<span class="stamp" style="color:var(--bad)">Jira: ${data.jira_error}</span>`}
      ${data?.time_error && html`<span class="stamp" style="color:var(--bad)">время: ${data.time_error}</span>`}
      ${data?.tokens_error && html`<span class="stamp" style="color:var(--bad)">токены: ${data.tokens_error}</span>`}
      <span class="stamp">${data ? `снимок ${stamp(data.generated)}` : ''}</span>
      <button class="btn" disabled=${busy} onClick=${() => load(true)}>
        ${busy ? html`<span class="spin"></span>` : '↻'} обновить
      </button>
    </div></header>
    <main class="main">
      <${Facts} facts=${data?.facts} limits=${data?.limits || []} />
      <${Chart} chart=${data?.chart} />
      ${data && !rows.length ? html`<div class="empty">задач нет</div>` : html`
      <table>
        <thead><tr><th>ключ</th><th>проект</th><th>название</th><th>стадия</th><th>Jira</th><th>PR</th><th>время</th><th>токены / $</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`}
      ${folded.length ? html`<button class="fold" onClick=${() => setShowFolded(!showFolded)}>
        ${showFolded ? '▾' : '▸'} без движения > 14 дн: ${folded.length}</button>` : null}
      ${data?.errors?.length ? html`<div class="errors">не прочитаны: ${data.errors.join('; ')}</div>` : null}
    </main>`;
}

render(html`<${App} />`, document.getElementById('app'));
