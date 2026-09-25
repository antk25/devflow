import { html, render, useState, useEffect, useRef, useMemo } from './vendor/preact-htm.mjs';

const WD = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];
const WD_LONG = ['понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота', 'воскресенье'];
const MONTHS = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const SHEETS = { client: ['Клиент', 'var(--s1)'], employer: ['Работодатель', 'var(--s2)'] };
const MIRROR_FLAGS = ['no-mirror', 'ambiguous-mirror', 'create-mirror', 'mirror-unavailable'];
const SKIP = ['no-mirror', 'ambiguous-mirror', 'overflow', 'mirror-unavailable', 'create-mirror', 'empty-day'];
const KEY_RE = /^[A-Z][A-Z0-9]+-\d+$/;
const FLAGS = {
  'no-mirror': ['нет зеркала', m => `Для ${m || 'задачи клиента'} не нашлась задача-зеркало. В Jira строка не уйдёт, пока не вписан ключ.`],
  'create-mirror': ['заведите зеркало', m => `Зеркала для ${m || 'задачи клиента'} нет. Заведите задачу у работодателя и впишите её ключ в строку.`],
  'ambiguous-mirror': ['зеркал несколько', m => `Для ${m || 'задачи клиента'} нашлось несколько задач-зеркал. Впишите нужный ключ вручную.`],
  'mirror-unavailable': ['зеркала не проверены', () => 'Jira работодателя не ответила, зеркала не искались. Пересчитайте позже.'],
  'overflow': ['сверх нормы', () => 'Предложено больше нормы дня. В Jira строка не уйдёт, пока не поправлены часы.'],
  'empty-day': ['нет активности', () => 'Будний день без ворклогов и без активности в транскриптах. Добавьте запись вручную.'],
};

const pad = n => String(n).padStart(2, '0');
const toDate = iso => { const [y, m, d] = iso.split('-').map(Number); return new Date(y, m - 1, d); };
const isoOf = t => `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`;
const wdi = iso => (toDate(iso).getDay() + 6) % 7;
const dayNum = iso => toDate(iso).getDate();
const shortDay = iso => `${WD[wdi(iso)]} ${pad(dayNum(iso))}.${pad(toDate(iso).getMonth() + 1)}`;
const longDay = iso => `${WD_LONG[wdi(iso)]}, ${dayNum(iso)} ${MONTHS[toDate(iso).getMonth()]}`;
const h = sec => String(Math.round(sec / 36) / 100).replace('.', ',');
const plural = (n, [one, few, many]) => {
  const a = n % 10, b = n % 100;
  return a === 1 && b !== 11 ? one : a >= 2 && a <= 4 && (b < 12 || b > 14) ? few : many;
};

export function parseHours(v) {
  const s = String(v).trim().toLowerCase().replace(/\s+/g, '');
  let m, min = NaN;
  if ((m = s.match(/^(\d{1,2}):([0-5]\d)$/))) min = +m[1] * 60 + +m[2];
  else if ((m = s.match(/^\d+(?:[.,]\d+)?$/))) min = parseFloat(s.replace(',', '.')) * 60;
  else if ((m = s.match(/^(?:(\d+(?:[.,]\d+)?)(?:ч|h))?(?:(\d+)(?:мин|м|min|m)?)?$/)) && (m[1] || m[2]))
    min = (m[1] ? parseFloat(m[1].replace(',', '.')) * 60 : 0) + (m[2] ? +m[2] : 0);
  return min > 0 && min <= 24 * 60 ? Math.round(min) * 60 : NaN;
}

function weekLabel(start, end) {
  const a = toDate(start), b = toDate(end);
  return a.getMonth() === b.getMonth()
    ? `${a.getDate()}–${b.getDate()} ${MONTHS[b.getMonth()]} ${b.getFullYear()}`
    : `${a.getDate()} ${MONTHS[a.getMonth()]} – ${b.getDate()} ${MONTHS[b.getMonth()]} ${b.getFullYear()}`;
}

function shift(w, n) {
  const [y, k] = w.split('-W').map(Number);
  const monday = y => { const j4 = new Date(Date.UTC(y, 0, 4)); return j4.getTime() - ((j4.getUTCDay() + 6) % 7) * 864e5; };
  const mon = monday(y) + ((k - 1 + n) * 7) * 864e5;
  const y2 = new Date(mon + 3 * 864e5).getUTCFullYear();
  return `${y2}-W${pad(1 + Math.round((mon - monday(y2)) / (7 * 864e5)))}`;
}

async function api(path, method = 'GET', body) {
  const r = await fetch(`/api/week/${path}`, {
    method, headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let j = {};
  try { j = await r.json(); } catch { /* пустое тело */ }
  if (!r.ok) throw Object.assign(new Error(j.error || `сервер ответил ${r.status}`), { status: r.status });
  return j;
}

function hintsFor(hints, key) {
  const k = (key || '').trim().toUpperCase();
  if (!k) return [];
  return [...new Set([...(hints[k] || []), ...(hints[k.split('-')[0]] || [])])].slice(0, 8);
}

function buildSheet(data, name) {
  const s = data.sheets[name];
  if (s.unavailable) return { name, s };
  const days = s.days.map(d => d.day);
  const rows = new Map();
  const row = (key, mirror) => {
    const id = key || `?${mirror || ''}`;
    if (!rows.has(id)) rows.set(id, { id, key, mirror: '', flags: new Set(), cells: {}, logged: 0, pending: 0 });
    const r = rows.get(id);
    if (mirror && !r.mirror) r.mirror = mirror;
    return r;
  };
  const put = (r, e) => {
    const c = r.cells[e.day] ??= { jira: [], draft: [], manual: [], logged: 0, pending: 0, flags: new Set() };
    c[e.kind].push(e);
    if (e.kind === 'jira') { c.logged += e.seconds; r.logged += e.seconds; return; }
    c.pending += e.seconds; r.pending += e.seconds;
    for (const f of e.flags) { c.flags.add(f); r.flags.add(f); }
  };
  for (const w of s.worklogs) put(row(w.key), { kind: 'jira', ...w, flags: [] });
  const manual = (data.manual || []).map((m, mi) => ({ ...m, mi })).filter(m => m.sheet === name);
  const used = new Set(), empty = new Set();
  (data.draft?.lines || []).forEach((l, i) => {
    if (l.sheet !== name) return;
    if (l.flags.includes('empty-day')) { empty.add(l.day); return; }
    const m = l.source === 'manual'
      ? manual.find(m => !used.has(m.mi) && m.day === l.day && m.key === l.key && m.seconds === l.seconds) : null;
    if (m) used.add(m.mi);
    if (l.sent_id) return;
    put(row(l.key, l.mirror_of), {
      kind: l.source === 'manual' ? 'manual' : 'draft', i, mi: m ? m.mi : null, sheet: name, day: l.day, key: l.key,
      seconds: l.seconds, comment: l.comment, flags: l.flags, edited: l.edited, mirror: l.mirror_of,
    });
  });
  for (const m of manual) {
    if (used.has(m.mi) || s.worklogs.some(w => w.key === m.key && w.day === m.day && w.seconds === m.seconds)) continue;
    put(row(m.key), { kind: 'manual', i: null, mi: m.mi, sheet: name, day: m.day, key: m.key, seconds: m.seconds,
      comment: m.comment, flags: [] });
  }
  const order = r => { const [p, n] = r.key.split('-'); return [r.key ? 0 : 1, p, +n || 0]; };
  const list = [...rows.values()].sort((a, b) => {
    const [xa, pa, na] = order(a), [xb, pb, nb] = order(b);
    return xa - xb || pa.localeCompare(pb) || na - nb || a.id.localeCompare(b.id);
  });
  const totals = Object.fromEntries(days.map(d => [d, { logged: 0, pending: 0 }]));
  for (const r of list) for (const [d, c] of Object.entries(r.cells)) {
    if (!totals[d]) continue;
    totals[d].logged += c.logged; totals[d].pending += c.pending;
  }
  const logged = list.reduce((a, r) => a + r.logged, 0), pending = list.reduce((a, r) => a + r.pending, 0);
  return { name, s, days, rows: list, totals, empty, logged, pending };
}

function pendingPlan(data) {
  const pool = new Map();
  const sig = (sheet, key, day, sec, comment) => [sheet, key.toUpperCase(), day, sec, (comment || '').trim()].join('|');
  for (const [name, s] of Object.entries(data.sheets))
    for (const w of s.worklogs || []) { const k = sig(name, w.key, w.day, w.seconds, w.comment); pool.set(k, (pool.get(k) || 0) + 1); }
  let count = 0, seconds = 0, skipped = 0;
  for (const l of data.draft?.lines || []) {
    if (l.flags.includes('empty-day')) continue;
    if (data.sheets[l.sheet]?.unavailable || l.flags.some(f => SKIP.includes(f)) || !l.key || l.seconds <= 0) { skipped++; continue; }
    if (l.sent_id) continue;
    const k = sig(l.sheet, l.key, l.day, l.seconds, l.comment);
    if (pool.get(k) > 0) { pool.set(k, pool.get(k) - 1); continue; }
    count++; seconds += l.seconds;
  }
  return { count, seconds, skipped };
}

function dayState(total, norm, weekend) {
  if (weekend) return total ? 'we' : 'none';
  return total < norm ? 'under' : total > norm ? 'over' : 'ok';
}

function Bar({ logged, pending, norm }) {
  const scale = Math.max(norm, logged + pending) || 1;
  const over = Math.max(0, logged + pending - norm);
  const pct = v => `${(v / scale) * 100}%`;
  return html`<div class="bar" aria-hidden="true">
    <i class="l" style=${{ width: pct(Math.min(logged, norm)) }}></i>
    <i class="p" style=${{ width: pct(Math.max(0, Math.min(pending, norm - logged))) }}></i>
    <i class="o" style=${{ width: pct(over) }}></i>
  </div>`;
}

function Flag({ f, mirror }) {
  const [label, tip] = FLAGS[f] || [f, () => f];
  return html`<span class="tag warn" title=${tip(mirror)}>${label}</span>`;
}

function Cell({ sheet, row, day, r, c, selected, onOpen }) {
  const cls = ['c'];
  if (c?.logged) cls.push('log');
  if (c?.draft.length) cls.push('dr');
  if (c?.manual.length) cls.push('mn');
  if (c?.flags.size) cls.push('fl');
  if (selected) cls.push('sel');
  const parts = [];
  if (c?.logged) parts.push(`в Jira ${h(c.logged)} ч`);
  if (c?.pending) parts.push(`к записи ${h(c.pending)} ч`);
  const comments = c ? [...c.jira, ...c.draft, ...c.manual].map(e => e.comment).filter(Boolean) : [];
  const label = `${row.key || 'без задачи'}, ${longDay(day)}: ${parts.join(', ') || 'пусто, добавить запись'}`;
  return html`<button class=${cls.join(' ')} data-r=${r} data-c=${day} data-sheet=${sheet} aria-label=${label}
      title=${[...new Set(comments)].join(' · ') || undefined} onClick=${() => onOpen(row.id, day)}>
    ${c?.logged ? html`<span class="lg">${h(c.logged)}</span>` : ''}
    ${c?.pending ? html`<span class="pd">${c.logged ? '+' : ''}${h(c.pending)}</span>` : ''}
    ${!c?.logged && !c?.pending ? html`<span class="plus">+</span>` : ''}
  </button>`;
}

function arrowNav(e) {
  const d = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] }[e.key];
  const t = e.target.closest('button.c');
  if (!d || !t) return;
  const table = t.closest('table');
  const cols = [...table.querySelectorAll('thead th[data-day]')].map(th => th.dataset.day);
  const r = +t.dataset.r + d[0], c = cols[cols.indexOf(t.dataset.c) + d[1]];
  const next = c && table.querySelector(`button.c[data-r="${r}"][data-c="${c}"]`);
  if (next) { e.preventDefault(); next.focus(); }
}

function SheetPanel({ m, sel, today, dim, onOpen, onAdd }) {
  const [title, color] = SHEETS[m.name] || [m.name, 'var(--ink-3)'];
  const head = html`<h2><span class="dot" style=${{ background: color }}></span>${title}
    ${m.s.account ? html`<span class="acc">${m.s.account}</span>` : ''}</h2>`;
  if (m.s.unavailable) {
    return html`<section class="sheet"><div class="sh">${head}</div>
      <div style="padding:1rem"><div class="note warn" style="margin:0"><p><b>Нет доступа к Jira.</b> ${m.s.unavailable}</p></div></div></section>`;
  }
  const { norm_day: norm, norm_week: normWeek } = m.s;
  const total = m.logged + m.pending, weekState = dayState(total, normWeek, false);
  const isSel = (row, day) => sel && sel.sheet === m.name && sel.rowId === row && sel.day === day;
  return html`<section class=${`sheet${dim ? ' dim' : ''}`} aria-label=${title}>
    <div class="sh">
      ${head}
      <div class="meter">
        <div class="v num"><b>${h(total)}</b> <span class="muted">из ${h(normWeek)} ч</span></div>
        <${Bar} logged=${m.logged} pending=${m.pending} norm=${normWeek} />
        <div class="sub">в Jira ${h(m.logged)} · к записи ${h(m.pending)}</div>
      </div>
    </div>
    <div class="tw">
      <table class="grid" onKeyDown=${arrowNav}>
        <colgroup><col class="k" />${m.days.map((d, i) => html`<col class=${i >= 5 ? 'we' : ''} />`)}<col class="t" /></colgroup>
        <thead><tr>
          <th class="kh" scope="col">Задача</th>
          ${m.days.map((d, i) => html`<th scope="col" data-day=${d} class=${[i >= 5 ? 'we' : '', d === today ? 'today' : ''].join(' ')}
              title=${i >= 5 ? 'Выходной: активность переносится на понедельник' : undefined}>
            ${WD[i]}<b>${dayNum(d)}</b></th>`)}
          <th scope="col">Итого</th>
        </tr></thead>
        <tbody>
          ${m.rows.map((row, r) => html`<tr key=${row.id}>
            <td class="kc">
              <div class="kline">
                <span class=${`key mono${row.key ? '' : ' none'}`}>${row.key || 'без задачи'}</span>
                ${row.mirror ? html`<span class="mirror" title=${`зеркало ${row.mirror}`}>← ${row.mirror}</span>` : ''}
              </div>
              ${row.flags.size ? html`<div class="tags">${[...row.flags].map(f => html`<${Flag} f=${f} mirror=${row.mirror} />`)}</div>` : ''}
            </td>
            ${m.days.map((d, i) => html`<td class=${i >= 5 ? 'we' : ''}>
              <${Cell} sheet=${m.name} row=${row} day=${d} r=${r} c=${row.cells[d]} selected=${isSel(row.id, d)} onOpen=${(id, day) => onOpen(m.name, id, day)} />
            </td>`)}
            <td class="rt">${h(row.logged + row.pending)}</td>
          </tr>`)}
          ${!m.rows.length ? html`<tr><td colspan="9" class="muted" style="padding:1rem">
            За эту неделю ни ворклогов, ни черновика. Нажмите «Пересчитать» или добавьте запись.</td></tr>` : ''}
        </tbody>
        <tfoot><tr>
          <td class="kc">За день<span class="muted">норма ${h(norm)} ч</span></td>
          ${m.days.map((d, i) => {
            const t = m.totals[d], sum = t.logged + t.pending, st = dayState(sum, norm, i >= 5);
            const past = d <= today;
            const note = m.empty.has(d) ? 'нет активности'
              : st === 'under' && past ? `не хватает ${h(norm - sum)}` : st === 'over' ? `лишние ${h(sum - norm)}` : '';
            return html`<td class=${`ft ${st === 'under' && !past ? 'none' : st}${i >= 5 ? ' we' : ''}`}
                title=${m.empty.has(d) ? FLAGS['empty-day'][1]() : `в Jira ${h(t.logged)} ч, к записи ${h(t.pending)} ч`}>
              <div class="v">${sum || i < 5 ? html`<b>${h(sum)}</b>` : html`<span>—</span>`}${i < 5 ? html`<span>/${h(norm)}</span>` : ''}</div>
              ${i < 5 || sum ? html`<${Bar} logged=${t.logged} pending=${t.pending} norm=${i < 5 ? norm : sum} />` : ''}
              <span class="st">${note || ' '}</span>
            </td>`;
          })}
          <td class=${`ft ${weekState}`}><div class="v"><b>${h(total)}</b></div><span class="st">из ${h(normWeek)}</span></td>
        </tr></tfoot>
      </table>
    </div>
    <div class="sheet-foot"><button class="btn ghost sm" onClick=${() => onAdd(m.name)}>+ Строка</button></div>
  </section>`;
}

function Skeleton() {
  return [0, 1].map(k => html`<section class="sheet" key=${k} aria-hidden="true">
    <div class="sh"><div class="sk" style="width:9rem;height:1.3rem"></div><div class="sk" style="width:16rem;height:1.3rem;margin-left:auto"></div></div>
    ${[0, 1, 2, 3, 4, 5].map(i => html`<div class="sk-row" key=${i}>${Array.from({ length: 9 }, (_, j) => html`<div class="sk" key=${j}></div>`)}</div>`)}
  </section>`);
}

function CommentField({ value, onInput, hints, disabled }) {
  const id = useMemo(() => `h${Math.random().toString(36).slice(2)}`, []);
  return html`<div class="full">
    <label class="f">Комментарий
      <input class="in" name="comment" list=${id} value=${value} disabled=${disabled} placeholder="например, Meeting" onInput=${e => onInput(e.target.value)} />
    </label>
    <datalist id=${id}>${hints.map(c => html`<option value=${c} />`)}</datalist>
    ${hints.length ? html`<div class="chips" aria-label="Частые комментарии">
      ${hints.slice(0, 5).map(c => html`<button type="button" class=${`chip${c === value ? ' on' : ''}`} disabled=${disabled}
        onClick=${() => onInput(c === value ? '' : c)}>${c}</button>`)}</div>` : ''}
  </div>`;
}

function PendingCard({ e, hints, busy, act }) {
  const [key, setKey] = useState(e.key);
  const [hrs, setHrs] = useState(h(e.seconds));
  const [comment, setComment] = useState(e.comment || '');
  const [err, setErr] = useState('');
  const sec = parseHours(hrs), k = key.trim().toUpperCase();
  const changed = k !== e.key || sec !== e.seconds || comment !== (e.comment || '');
  const mirrorFix = e.flags.some(f => MIRROR_FLAGS.includes(f)), overFix = e.flags.includes('overflow');
  const dirty = changed || mirrorFix || overFix;
  const save = async () => {
    if (!KEY_RE.test(k)) return setErr('Укажите ключ задачи, например GS-1258');
    if (!Number.isFinite(sec)) return setErr('Часы: 1,5 или 1.5 или 1:30');
    setErr('');
    const body = {};
    if (k !== e.key || mirrorFix) body.key = k;
    if (sec !== e.seconds || overFix) body.seconds = sec;
    if (comment !== (e.comment || '')) body.comment = comment;
    const ok = e.kind === 'manual' && e.mi !== null
      ? await act.replaceManual(e, { key: k, seconds: sec, comment }) : await act.editDraft(e.i, body);
    if (ok && k !== e.key) act.follow(k);
  };
  const del = () => (e.kind === 'manual' && e.mi !== null ? act.deleteManual(e.mi) : act.deleteDraft(e.i));
  const onKey = ev => { if (ev.key === 'Enter' && ev.target.tagName === 'INPUT') { ev.preventDefault(); if (dirty) save(); } };
  return html`<div class=${`card ${e.kind === 'manual' ? 'mn' : 'dr'}`} onKeyDown=${onKey}>
    <div class="tags">
      ${e.kind === 'manual' ? html`<span class="tag mn" title="Добавлена вами; при пересчёте день раскладывается вокруг неё">ручная</span>`
        : html`<span class="tag dr" title="Предложено по активности в транскриптах">черновик</span>`}
      ${e.edited ? html`<span class="tag" title="Поправлена вами; пересчёт её не перезапишет">поправлена</span>` : ''}
      ${e.flags.map(f => html`<${Flag} f=${f} mirror=${e.mirror} />`)}
    </div>
    ${e.flags.filter(f => FLAGS[f]).map(f => html`<p class="flag-why">${FLAGS[f][1](e.mirror)}</p>`)}
    <div class="fields k3">
      <label class="f">Задача<input name="key" class=${`in k${!e.key && !key ? ' err' : ''}`} value=${key} placeholder="GS-…" disabled=${busy}
        onInput=${ev => setKey(ev.target.value)} /></label>
      <label class="f">Часы<input name="hours" class=${`in h${Number.isFinite(sec) ? '' : ' err'}`} value=${hrs} inputmode="decimal" disabled=${busy}
        onInput=${ev => setHrs(ev.target.value)} /></label>
      <span></span>
      <${CommentField} value=${comment} onInput=${setComment} hints=${hintsFor(hints, k)} disabled=${busy} />
    </div>
    ${err ? html`<div class="ferr">${err}</div>` : ''}
    <div class="row-btns">
      <button class="btn primary sm" disabled=${busy || !dirty} onClick=${save}
        title=${!changed && dirty ? 'Принять строку как есть: метка снимется, строка уйдёт в Jira' : undefined}>
        ${!changed && dirty ? 'Подтвердить' : 'Сохранить'}</button>
      <span class="sp"></span>
      <button class="btn ghost sm danger" disabled=${busy} onClick=${del}
        title=${e.kind === 'manual' ? 'Удалить ручную запись' : 'Убрать из черновика; пересчёт её не вернёт'}>Удалить</button>
    </div>
  </div>`;
}

function JiraCard({ e, hints, busy, act }) {
  const [hrs, setHrs] = useState(h(e.seconds));
  const [comment, setComment] = useState(e.comment || '');
  const [ask, setAsk] = useState(null);
  const sec = parseHours(hrs);
  const dirty = sec !== e.seconds || comment !== (e.comment || '');
  const editable = !!e.id;
  const body = () => ({ ...(sec !== e.seconds ? { seconds: sec } : {}), ...(comment !== (e.comment || '') ? { comment } : {}) });
  const onKey = ev => {
    if (ev.key === 'Escape' && ask) { ev.stopPropagation(); setAsk(null); }
    if (ev.key === 'Enter' && ev.target.tagName === 'INPUT') { ev.preventDefault(); if (dirty && Number.isFinite(sec)) setAsk('save'); }
  };
  const run = async fn => { const ok = await fn(); if (ok) setAsk(null); };
  const changes = [sec !== e.seconds ? `часы ${h(e.seconds)} → ${h(sec)}` : '',
    comment !== (e.comment || '') ? `комментарий «${comment || 'пусто'}»` : ''].filter(Boolean).join(', ');
  return html`<div class="card log" onKeyDown=${onKey}>
    <div class="tags"><span class="tag ok">в Jira</span>${e.id ? html`<span class="tag mono" title="Номер ворклога">#${e.id}</span>` : ''}</div>
    <div class="fields">
      <label class="f">Часы<input name="hours" class=${`in h${Number.isFinite(sec) ? '' : ' err'}`} value=${hrs} inputmode="decimal"
        disabled=${busy || !editable} onInput=${ev => { setHrs(ev.target.value); setAsk(null); }} /></label>
      <span></span>
      <${CommentField} value=${comment} onInput=${v => { setComment(v); setAsk(null); }} hints=${hintsFor(hints, e.key)} disabled=${busy || !editable} />
    </div>
    ${ask === 'save' ? html`<div class="confirm chg" role="alert">
        Изменить ворклог в Jira: ${changes}? Правка уходит в Jira сразу.
        <div class="row-btns"><button class="btn primary sm" disabled=${busy} onClick=${() => run(() => act.editSent(e, body()))}>Изменить в Jira</button>
        <button class="btn sm" onClick=${() => setAsk(null)}>Отмена</button></div></div>`
      : ask === 'delete' ? html`<div class="confirm" role="alert">
        Удалить из Jira ворклог ${e.key} на ${h(e.seconds)} ч? Вернуть его можно только новой записью.
        <div class="row-btns"><button class="btn danger solid sm" disabled=${busy} onClick=${() => run(() => act.deleteSent(e))}>Удалить из Jira</button>
        <button class="btn sm" onClick=${() => setAsk(null)}>Отмена</button></div></div>`
      : editable ? html`<div class="row-btns">
        <button class="btn sm" disabled=${busy || !dirty || !Number.isFinite(sec)} onClick=${() => setAsk('save')}>Изменить в Jira…</button>
        <span class="sp"></span>
        <button class="btn ghost sm danger" disabled=${busy} onClick=${() => setAsk('delete')}>Удалить из Jira…</button></div>`
      : html`<div class="hint muted" style="margin-top:.4rem">Номера ворклога нет — править можно только в Jira.</div>`}
  </div>`;
}

function AddForm({ sheet, day, days, initialKey, hints, busy, act }) {
  const [key, setKey] = useState(initialKey || '');
  const [d, setD] = useState(day);
  const [hrs, setHrs] = useState('');
  const [comment, setComment] = useState('');
  const [err, setErr] = useState('');
  const submit = async ev => {
    ev.preventDefault();
    const k = key.trim().toUpperCase(), sec = parseHours(hrs);
    if (!KEY_RE.test(k)) return setErr('Укажите ключ задачи, например SE-188');
    if (!d) return setErr('Выберите день');
    if (!Number.isFinite(sec)) return setErr('Часы: 1,5 или 1.5 или 1:30');
    setErr('');
    if (await act.addManual({ sheet, day: d, key: k, seconds: sec, comment })) { setHrs(''); setComment(''); }
  };
  return html`<form class="card mn" onSubmit=${submit}>
    ${days ? html`<div class="full" style="margin-bottom:.45rem"><div class="f" style="font-size:.75rem;color:var(--ink-3);margin-bottom:.15rem">День</div>
      <div class="daypick">${days.map((x, i) => html`<button type="button" class=${x === d ? 'on' : ''} aria-pressed=${x === d} onClick=${() => setD(x)}>${WD[i]} ${dayNum(x)}</button>`)}</div></div>` : ''}
    <div class="fields k3">
      <label class="f">Задача<input name="key" class="in k" value=${key} placeholder="SE-188" disabled=${busy} onInput=${e => setKey(e.target.value)} /></label>
      <label class="f">Часы<input name="hours" class="in h" value=${hrs} inputmode="decimal" placeholder="1,5" disabled=${busy} onInput=${e => setHrs(e.target.value)} /></label>
      <span></span>
      <${CommentField} value=${comment} onInput=${setComment} hints=${hintsFor(hints, key)} disabled=${busy} />
    </div>
    ${err ? html`<div class="ferr">${err}</div>` : ''}
    <div class="row-btns"><button class="btn primary sm" type="submit" disabled=${busy}>Добавить</button></div>
  </form>`;
}

function Drawer({ sel, model, hints, busy, act, onClose }) {
  const m = model[sel.sheet];
  const row = sel.rowId ? m.rows.find(r => r.id === sel.rowId) : null;
  const cell = row && sel.day ? row.cells[sel.day] : null;
  const key = row?.key ?? (sel.rowId && !sel.rowId.startsWith('?') ? sel.rowId : '');
  const pending = cell ? [...cell.manual, ...cell.draft] : [];
  const title = SHEETS[sel.sheet]?.[0] || sel.sheet;
  const ek = e => `${e.kind}-${e.i}-${e.mi}-${e.id}-${e.key}-${e.seconds}-${e.comment}`;
  const ref = useRef();
  useEffect(() => {
    const first = ref.current.querySelector(key ? 'input.h:not(:disabled)' : 'input.k');
    first?.focus(); first?.select();
  }, [sel.sheet, sel.rowId, sel.day, sel.adding]);
  return html`<aside class="drawer" ref=${ref} aria-label="Записи ячейки" onKeyDown=${ev => { if (ev.key === 'Escape') { ev.stopPropagation(); onClose(); } }}>
    <div class="dh">
      <div class="t">
        <div class="t1">${sel.adding ? 'Новая строка' : html`<span class="mono">${key || 'без задачи'}</span>
          ${row?.mirror ? html`<span class="mirror">← ${row.mirror}</span>` : ''}`}</div>
        <div class="t2">${title}${sel.day && !sel.adding ? ` · ${longDay(sel.day)}` : ''}</div>
      </div>
      <button class="btn ghost icon" onClick=${onClose} aria-label="Закрыть" title="Закрыть (Esc)">×</button>
    </div>
    ${cell ? html`<div class="dsum">
      <span>Всего <b>${h(cell.logged + cell.pending)}</b> ч</span>
      <span>в Jira <b>${h(cell.logged)}</b></span>
      <span>к записи <b>${h(cell.pending)}</b></span></div>` : ''}
    ${cell?.jira.length ? html`<div class="dsec"><h3>Уже в Jira</h3>
      <p class="hint">Правка и удаление уходят в Jira сразу, после подтверждения.</p>
      ${cell.jira.map(e => html`<${JiraCard} key=${ek(e)} e=${e} hints=${hints} busy=${busy} act=${act} />`)}</div>` : ''}
    ${pending.length ? html`<div class="dsec"><h3>К записи</h3>
      ${pending.map(e => html`<${PendingCard} key=${ek(e)} e=${e} hints=${hints} busy=${busy} act=${act} />`)}</div>` : ''}
    <div class="dsec"><h3>${sel.adding ? 'Ручная запись' : 'Добавить ручную запись'}</h3>
      <p class="hint">Встречи, созвоны — то, чего нет в транскриптах. Ручная запись главнее черновика: при пересчёте остаток дня раскладывается вокруг неё.</p>
      <${AddForm} key=${`${sel.sheet}-${sel.rowId}-${sel.day}`} sheet=${sel.sheet} day=${sel.day} days=${sel.adding ? m.days : null}
        initialKey=${key} hints=${hints} busy=${busy} act=${act} />
    </div>
    <div class="kbd"><kbd>Enter</kbd> сохранить · <kbd>Esc</kbd> закрыть · стрелки — по ячейкам</div>
  </aside>`;
}

function PlanDialog({ week, onClose, onApplied, toast }) {
  const ref = useRef();
  const [plan, setPlan] = useState(null);
  const [phase, setPhase] = useState('loading');
  const [err, setErr] = useState('');
  const [results, setResults] = useState(null);
  const load = async () => {
    setPhase('loading'); setErr('');
    try { setPlan(await api(`${week}/plan`)); setPhase('ready'); } catch (e) { setErr(e.message); setPhase('error'); }
  };
  useEffect(() => { ref.current.showModal(); load(); }, []);
  const sheets = plan ? Object.entries(plan.sheets) : [];
  const count = sheets.reduce((a, [, s]) => a + s.actions.length, 0);
  const total = sheets.reduce((a, [, s]) => a + s.total, 0);
  const send = async () => {
    setPhase('sending');
    try {
      const j = await api(`${week}/apply`, 'POST', { hash: plan.hash });
      onApplied(j); setResults(j.results); setPhase('done');
    } catch (e) {
      if (e.status === 409) { toast(e.message, 'warn'); return load(); }
      setErr(e.message); setPhase('ready');
    }
  };
  const why = s => s.split(', ').map(f => FLAGS[f]?.[0] || f).join(', ');
  const row = (a, extra, cls) => html`<tr class=${cls}><td class="d">${shortDay(a.day)}</td>
    <td class="k">${a.key || 'без задачи'}${a.mirror_of ? html` <span class="muted">← ${a.mirror_of}</span>` : ''}</td>
    <td class="n">${h(a.seconds)}</td><td>${extra}</td></tr>`;
  const bad = results ? results.filter(x => x.error) : [];
  return html`<dialog class="plan" ref=${ref} onCancel=${e => { e.preventDefault(); if (phase !== 'sending') onClose(); }}
      aria-labelledby="plan-title">
    <div class="pl">
      <div class="pl-h"><h2 id="plan-title">Запись в Jira · ${week}</h2></div>
      <div class="pl-b">
        ${phase === 'done' ? html`
          <div class=${`note ${bad.length ? 'bad' : ''}`}><p>Записано ${results.length - bad.length} из ${results.length}.
            ${bad.length ? ` Ошибок: ${bad.length} — строки остались в черновике.` : ''}</p></div>
          ${bad.map(x => html`<div class="note bad"><p>${shortDay(x.day)} ${x.key}: ${x.error}</p></div>`)}`
        : html`
          <div class="note warn"><p><b>Сервер пишет в Jira напрямую, без подтверждения Claude.</b>${' '}
            Это окно — единственная проверка: сверьте список построчно.</p></div>
          ${phase === 'loading' ? html`<p class="muted">Сверяю черновик с Jira…</p>` : ''}
          ${err ? html`<div class="note bad"><p>${err}</p></div>` : ''}
          ${plan && phase !== 'loading' ? (sheets.length ? sheets.map(([name, s]) => html`
            <h3><span class="dot" style=${{ background: SHEETS[name]?.[1] || 'var(--ink-3)' }}></span>${SHEETS[name]?.[0] || name}
              <span class="muted">${s.actions.length} ${plural(s.actions.length, ['запись', 'записи', 'записей'])}, ${h(s.total)} ч</span></h3>
            <table class="lst"><tbody>
              ${s.actions.map(a => row(a, a.comment))}
              ${s.skipped.map(a => row(a, html`<span class="tag warn">не записывается: ${why(a.why)}</span>`, 'skip'))}
            </tbody></table>`) : html`<p class="muted">Записывать нечего: всё из черновика уже в Jira.</p>`) : ''}`}
      </div>
      <div class="pl-f">
        ${phase === 'done' ? html`<button class="btn primary" onClick=${onClose}>Готово</button>` : html`
          <span class="sp">${plan && count ? `Итого ${count} ${plural(count, ['ворклог', 'ворклога', 'ворклогов'])}, ${h(total)} ч` : ''}</span>
          <button class="btn" onClick=${onClose} disabled=${phase === 'sending'}>Отмена</button>
          <button class="btn primary" onClick=${send} disabled=${phase !== 'ready' || !count}>
            ${phase === 'sending' ? html`<span class="spin"></span> Записываю…` : `Записать в Jira${count ? ` — ${count}` : ''}`}</button>`}
      </div>
    </div>
  </dialog>`;
}

function Toasts({ items, onClose }) {
  return html`<div class="toasts" role="status" aria-live="polite">
    ${items.map(t => html`<div class=${`toast ${t.kind}`} key=${t.id}><span>${t.text}</span>
      <button onClick=${() => onClose(t.id)} aria-label="Скрыть">×</button></div>`)}
  </div>`;
}

function App() {
  const [week, setWeek] = useState(location.hash.slice(1) || document.body.dataset.week);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [started, setStarted] = useState(null);
  const [saving, setSaving] = useState(0);
  const [, tick] = useState(0);
  const [sel, setSel] = useState(null);
  const [planOpen, setPlanOpen] = useState(false);
  const [toasts, setToasts] = useState([]);
  const req = useRef(0), lastCell = useRef(null), weekRef = useRef(week);
  weekRef.current = week;

  const toast = (text, kind = 'info') => {
    const id = Math.random();
    setToasts(t => [...t.slice(-3), { id, text, kind }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), kind === 'error' ? 9000 : 4000);
  };

  const load = async w => {
    const n = ++req.current;
    setLoading(true);
    try {
      const j = await api(w);
      if (n !== req.current) return;
      setData(j); setWeek(j.week);
      if (location.hash.slice(1) !== j.week) history.replaceState(null, '', `#${j.week}`);
    } catch (e) {
      if (n === req.current) toast(`Не удалось открыть неделю: ${e.message}`, 'error');
    } finally {
      if (n === req.current) setLoading(false);
    }
  };

  useEffect(() => { load(week); }, []);
  useEffect(() => {
    const on = () => { const w = location.hash.slice(1); if (w && w !== week) go(w); };
    addEventListener('hashchange', on);
    return () => removeEventListener('hashchange', on);
  });
  useEffect(() => {
    if (!started) return;
    const t = setInterval(() => tick(x => x + 1), 1000);
    return () => clearInterval(t);
  }, [started]);
  useEffect(() => {
    const on = e => { if (e.key === 'Escape' && sel && !planOpen) close(); };
    addEventListener('keydown', on);
    return () => removeEventListener('keydown', on);
  });

  const go = w => { setSel(null); setPlanOpen(false); setWeek(w); history.replaceState(null, '', `#${w}`); load(w); };

  const recompute = async () => {
    setStarted(Date.now());
    try {
      const j = await api(`${week}/recompute`, 'POST');
      if (j.week === weekRef.current) setData(j);
      toast('Черновик пересчитан');
    } catch (e) {
      toast(`Пересчёт не удался: ${e.message}`, 'error');
    } finally {
      setStarted(null);
    }
  };

  const mutate = async (path, method, body, ok) => {
    setSaving(n => n + 1);
    try {
      const j = await api(`${week}/${path}`, method, body);
      if (j.week === weekRef.current) setData(j);
      if (ok) toast(ok);
      return j;
    } catch (e) {
      toast(e.message, 'error');
      return null;
    } finally {
      setSaving(n => n - 1);
    }
  };

  const model = useMemo(() => data ? Object.fromEntries(Object.keys(data.sheets).map(n => [n, buildSheet(data, n)])) : {}, [data]);
  const pp = useMemo(() => data ? pendingPlan(data) : { count: 0, seconds: 0, skipped: 0 }, [data]);

  const act = {
    editDraft: (i, body) => mutate(`draft/${i}`, 'PUT', body, 'Строка сохранена'),
    deleteDraft: i => mutate(`draft/${i}`, 'DELETE', undefined, 'Строка убрана из черновика; пересчёт её не вернёт'),
    deleteManual: mi => mutate(`manual/${mi}`, 'DELETE', undefined, 'Ручная запись удалена'),
    replaceManual: async (e, body) => {
      if (!await mutate('manual', 'POST', { sheet: e.sheet, day: e.day, ...body })) return null;
      return mutate(`manual/${e.mi}`, 'DELETE', undefined, 'Ручная запись сохранена');
    },
    addManual: async body => {
      const j = await mutate('manual', 'POST', body);
      if (!j) return null;
      const m = buildSheet(j, body.sheet), t = m.totals?.[body.day], norm = j.sheets[body.sheet].norm_day;
      if (t && t.logged + t.pending > norm && j.draft)
        toast(`Запись добавлена. День теперь ${h(t.logged + t.pending)} ч из ${h(norm)} — «Пересчитать» ужмёт черновик вокруг неё.`, 'warn');
      else toast('Ручная запись добавлена');
      return j;
    },
    editSent: (e, body) => mutate(`sent/${e.id}`, 'PUT', { key: e.key, confirm: true, ...body }, 'Ворклог изменён в Jira'),
    follow: key => setSel(s => s && { ...s, rowId: key }),
    deleteSent: e => mutate(`sent/${e.id}`, 'DELETE', { key: e.key, confirm: true }, 'Ворклог удалён из Jira'),
  };

  const open = (sheet, rowId, day) => {
    lastCell.current = document.activeElement;
    setSel(s => s && s.sheet === sheet && s.rowId === rowId && s.day === day && !s.adding ? null : { sheet, rowId, day });
  };
  const add = sheet => {
    lastCell.current = document.activeElement;
    const m = model[sheet];
    const day = m.days.find(d => d <= today && m.totals[d].logged + m.totals[d].pending < m.s.norm_day && wdi(d) < 5) || m.days[0];
    setSel({ sheet, rowId: null, day, adding: true });
  };
  const close = () => {
    setSel(null);
    const el = lastCell.current;
    if (el && document.contains(el)) el.focus();
  };

  const today = isoOf(new Date());
  const busy = !!started || saving > 0;
  const current = data && data.week === data.current;
  const elapsed = started ? Math.floor((Date.now() - started) / 1000) : 0;
  const stamp = data?.draft?.generated
    ? `Черновик от ${data.draft.generated.slice(8, 10)}.${data.draft.generated.slice(5, 7)}, ${data.draft.generated.slice(11, 16)}`
    : data ? 'Черновика нет' : '';
  const names = data ? Object.keys(data.sheets) : [];

  return html`
    <div class="top">
      <div class="top-in">
        <span class="brand">Табель</span>
        <div class="wk">
          <button class="btn icon" onClick=${() => go(shift(week, -1))} disabled=${!!started} aria-label="Предыдущая неделя" title="Предыдущая неделя">‹</button>
          <div class="wk-label"><b>Неделя ${Number(week.split('-W')[1])}</b>
            <span>${data && data.week === week ? weekLabel(data.start, data.end) : ' '}</span></div>
          <button class="btn icon" onClick=${() => go(shift(week, 1))} disabled=${!!started} aria-label="Следующая неделя" title="Следующая неделя">›</button>
          <button class="btn sm ghost" onClick=${() => go(data.current)} disabled=${!data || current || !!started}
            style=${{ visibility: data && !current ? 'visible' : 'hidden' }}>К текущей</button>
        </div>
        <span class="grow"></span>
        <span class="stamp">${stamp}</span>
        <div class="actions">
          <button class="btn" onClick=${recompute} disabled=${!data || busy || loading}
            title="Заново собрать черновик из Jira и транскриптов; поправленные вами строки сохранятся">
            ${started ? html`<span class="spin"></span> Пересчитываю… ${elapsed} с` : '↻ Пересчитать'}</button>
          <button class="btn primary" onClick=${() => setPlanOpen(true)} disabled=${!data || busy || loading || !pp.count}
            title=${pp.skipped ? `Ещё ${pp.skipped} ${plural(pp.skipped, ['строка', 'строки', 'строк'])} не будут записаны — см. метки` : undefined}>
            ${pp.count ? html`<span class="wide">Записать в Jira —</span><span class="narrow">В Jira:</span>
              ${pp.count} ${plural(pp.count, ['запись', 'записи', 'записей'])}, ${h(pp.seconds)} ч` : 'Записывать нечего'}</button>
        </div>
      </div>
      <div class=${`progress${started || (loading && data) ? ' on' : ''}`}></div>
    </div>
    <div class=${`shell${sel && data ? ' open' : ''}`}>
      <main class="main">
        <div class="legend" aria-label="Обозначения">
          <span><i class="sw log"></i>уже в Jira</span>
          <span><i class="sw dr"></i>черновик, ещё не в Jira</span>
          <span><i class="sw mn"></i>ручная запись</span>
          <span><i class="sw fl"></i>требует внимания</span>
        </div>
        ${data && !loading && !data.draft ? html`<div class="note"><p><b>Черновика на эту неделю нет.</b>${' '}
          «Пересчитать» соберёт его из Jira и транскриптов — это до минуты.</p>
          <button class="btn" onClick=${recompute} disabled=${busy}>↻ Пересчитать</button></div>` : ''}
        ${data && !loading && pp.skipped ? html`<div class="note warn"><p>
          ${pp.skipped} ${plural(pp.skipped, ['строка', 'строки', 'строк'])} черновика не ${pp.skipped === 1 ? 'уйдёт' : 'уйдут'} в Jira — ${pp.skipped === 1 ? 'на ней метка' : 'на них метки'} вроде «нет зеркала». Откройте ячейку с жёлтой точкой: впишите ключ, поправьте часы или подтвердите строку как есть.</p></div>` : ''}
        ${!data || (loading && data.week !== week) ? html`<${Skeleton} />`
          : names.map(n => html`<${SheetPanel} key=${n} m=${model[n]} sel=${sel} today=${today} dim=${!!started}
              onOpen=${open} onAdd=${add} />`)}
      </main>
      ${sel && data && model[sel.sheet] && !model[sel.sheet].s.unavailable ? html`<${Drawer} sel=${sel} model=${model}
        hints=${data.hints || {}} busy=${busy} act=${act} onClose=${close} />` : ''}
    </div>
    ${planOpen ? html`<${PlanDialog} week=${week} onClose=${() => setPlanOpen(false)} toast=${toast}
      onApplied=${j => { setData(j); toast('Запись в Jira завершена'); }} />` : ''}
    <${Toasts} items=${toasts} onClose=${id => setToasts(t => t.filter(x => x.id !== id))} />`;
}

render(html`<${App} />`, document.getElementById('app'));
