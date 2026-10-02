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
    </tr>
    ${open && html`<tr class="detail"><td colSpan="4">
      <span class="mono muted">${t.slug}</span><br/>
      ${links.length ? links.map(([k, name]) => html`<a href=${obsidian(t.links[k])}>${name}</a>`)
        : html`<span class="muted">артефактов нет</span>`}
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
      rows.push(html`<tr class="sep" key=${'g' + group}><td colSpan="4">${GROUPS[group] || group}</td></tr>`);
    }
    rows.push(row(t));
  }
  if (showFolded && folded.length) {
    rows.push(html`<tr class="sep" key="gfolded"><td colSpan="4">без движения > 14 дн</td></tr>`);
    folded.forEach(t => rows.push(row(t)));
  }

  return html`
    <header class="top"><div class="top-in">
      <span class="brand"><a href="/">Табель</a> · Задачи</span>
      <span class="grow"></span>
      ${error && html`<span class="stamp" style="color:var(--bad)">${error}</span>`}
      <span class="stamp">${data ? `снимок ${stamp(data.generated)}` : ''}</span>
      <button class="btn" disabled=${busy} onClick=${() => load(true)}>
        ${busy ? html`<span class="spin"></span>` : '↻'} обновить
      </button>
    </div></header>
    <main class="main">
      ${data && !rows.length ? html`<div class="empty">задач нет</div>` : html`
      <table>
        <thead><tr><th>ключ</th><th>проект</th><th>название</th><th>стадия</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`}
      ${folded.length ? html`<button class="fold" onClick=${() => setShowFolded(!showFolded)}>
        ${showFolded ? '▾' : '▸'} без движения > 14 дн: ${folded.length}</button>` : null}
      ${data?.errors?.length ? html`<div class="errors">не прочитаны: ${data.errors.join('; ')}</div>` : null}
    </main>`;
}

render(html`<${App} />`, document.getElementById('app'));
