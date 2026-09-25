import hashlib
import json
import re
import subprocess
import threading
from collections import Counter
from dataclasses import asdict
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from devflow import timesheet as ts

HOST = '127.0.0.1'
SKILL_DIR = Path(__file__).resolve().parents[2] / 'skills'
INDEX = SKILL_DIR / 'timesheet' / 'index.html'
TOKENS = SKILL_DIR / 'page' / 'references' / 'tokens.css'
STATIC = {'/app.mjs': INDEX.parent / 'app.mjs', '/vendor/preact-htm.mjs': INDEX.parent / 'vendor' / 'preact-htm.mjs'}
MANUAL_FIELDS = ('sheet', 'day', 'key', 'seconds', 'comment')
MIRROR_FLAGS = ('no-mirror', 'ambiguous-mirror', 'create-mirror', 'mirror-unavailable')
ROUTE = re.compile(r'^/api/week/((?:\d{4}-)?W\d{1,2})(?:/(recompute|draft|manual|plan|apply|sent)(?:/(\d+))?)?$', re.I)
KEY = re.compile(r'^[A-Z][A-Z0-9]+-\d+$')


class BadRequest(ValueError):
    pass


class Conflict(ValueError):
    pass


def norm_week(week: str) -> str:
    return week.upper() if '-W' in week.upper() else ts.current_week(ts.week_range(week)[0])


def _json_default(v):
    if isinstance(v, date):
        return v.isoformat()
    raise TypeError(type(v))


class App:
    def __init__(self, rules, state=ts.STATE_DIR, fetch=ts.fetch_worklogs, compute=None, run=subprocess.run,
                 candidates=None):
        self.rules, self.state, self.fetch, self.run = rules, state, fetch, run
        self.candidates = candidates or (ts.week_candidates if fetch is ts.fetch_worklogs else lambda rules, logs: {})
        self.cands = {}
        self.write_lock = threading.Lock()
        self.compute = compute or (lambda rules, logs, week: ts.draft(
            rules, logs, ts.load_activity(rules, week), ts.load_manual(week, state), week))
        self.cache, self.lock = {}, threading.Lock()

    def _worklogs(self, week: str, fresh: bool = False) -> dict:
        with self.lock:
            if fresh or week not in self.cache:
                self.cache[week] = self.fetch(self.rules, week)
                self.cands.pop(week, None)
                ts.remember_comments(self.cache[week], self.state)
            return self.cache[week]

    def week(self, week: str) -> dict:
        logs = self._worklogs(week)
        start, end = ts.week_range(week)
        path = self.state / f'draft-{week}.json'
        draft = json.loads(path.read_text()) if path.exists() else None
        if {'client', 'employer'} <= set(self.rules.sheets):
            with self.lock:
                if week not in self.cands:
                    self.cands[week] = self.candidates(self.rules, logs)
            diff = ts.discrepancies(self.rules, logs, self.cands[week], week)
        else:
            diff = []
        sheets = {}
        for name, s in ts.summary(self.rules, logs, week).items():
            data = {k: v for k, v in s.items() if k != 'days'}
            if 'days' in s:
                data['days'] = [{'day': d, 'seconds': sec} for d, sec in s['days'].items()]
                data['worklogs'] = [asdict(w) for w in logs[name]]
            sheets[name] = data
        return {'week': week, 'start': start, 'end': end, 'current': ts.current_week(),
                'sheets': sheets, 'draft': draft, 'manual': ts.load_manual(week, self.state),
                'hints': ts.comment_hints(self.state), 'pending': self._pending(week, logs),
                'discrepancies': diff}

    def _pending(self, week: str, logs: dict) -> dict:
        out = {name: {'count': 0, 'seconds': 0, 'skipped': 0, 'days': {}} for name in self.rules.sheets}
        try:
            lines = ts.load_draft(week, self.state)
        except FileNotFoundError:
            return out
        actions, skipped = ts.plan_apply(lines, ts.load_sent(self.state), logs)
        for x in actions:
            day = out[x.sheet]['days'].setdefault(x.day.isoformat(), {'count': 0, 'seconds': 0})
            for d in (out[x.sheet], day):
                d['count'] += 1
                d['seconds'] += x.seconds
        for x, _ in skipped:
            if 'empty-day' not in x.flags:
                out[x.sheet]['skipped'] += 1
        return out

    def recompute(self, week: str) -> dict:
        logs = self._worklogs(week, fresh=True)
        lines = self.compute(self.rules, logs, week)
        with self.lock:
            old = self._read(week)
            lines = sync_manual(lines, ts.load_manual(week, self.state), logs, self.rules)
            ts.save_draft(week, merge_edits(lines, old), self.state)
            if old and old.get('removed'):
                self._write(week, {**self._read(week), 'removed': old['removed']})
        return self.week(week)

    def _read(self, week: str) -> dict | None:
        path = self.state / f'draft-{week}.json'
        return json.loads(path.read_text()) if path.exists() else None

    def _write(self, week: str, doc: dict) -> None:
        (self.state / f'draft-{week}.json').write_text(json.dumps(doc, ensure_ascii=False, indent=1))

    def _entry(self, week: str, body: dict, partial: dict | None = None) -> dict:
        e = dict(partial or {})
        for f in ('sheet', 'day', 'key', 'seconds', 'comment'):
            if f in body:
                e[f] = body[f]
        start, end = ts.week_range(week)
        if e.get('sheet') not in self.rules.sheets:
            raise BadRequest(f'нет табеля {e.get("sheet")!r}')
        try:
            day = date.fromisoformat(str(e.get('day')))
        except ValueError:
            raise BadRequest(f'плохая дата {e.get("day")!r}')
        if not start <= day <= end:
            raise BadRequest(f'{day} вне недели {week}')
        key = str(e.get('key', '')).strip().upper()
        if not KEY.match(key):
            raise BadRequest(f'плохой ключ задачи {key!r}')
        sec = e.get('seconds')
        if not isinstance(sec, (int, float)) or isinstance(sec, bool) or sec <= 0 or sec > 24 * 3600:
            raise BadRequest(f'плохие часы {sec!r}')
        return {**e, 'day': day.isoformat(), 'key': key, 'seconds': round(sec), 'comment': str(e.get('comment', ''))}

    def edit_line(self, week: str, i: int, body: dict | None) -> dict:
        with self.lock:
            doc = self._read(week)
            if not doc or not 0 <= i < len(doc['lines']):
                raise BadRequest(f'нет строки черновика #{i}')
            line = doc['lines'][i]
            if line.get('sent_id'):
                raise BadRequest('строка уже в Jira — правьте её в разделе отправленного')
            removed = doc.setdefault('removed', [])
            if line.get('key'):
                removed.append({'sheet': line['sheet'], 'day': line['day'], 'key': line['key']})
            if body is None:
                doc['lines'].pop(i)
            else:
                new = self._entry(week, body, line)
                drop = {'empty-day'}
                if str(body.get('key') or '').strip():
                    drop.update(MIRROR_FLAGS)
                if 'seconds' in body:
                    drop.add('overflow')
                flags = [f for f in line.get('flags', []) if f not in drop]
                doc['lines'][i] = {**line, **new, 'flags': flags, 'edited': True}
                sig = {'sheet': new['sheet'], 'day': new['day'], 'key': new['key']}
                doc['removed'] = [r for r in removed if r != sig]
            self._write(week, doc)
        return self.week(week)

    def add_manual(self, week: str, body: dict) -> dict:
        entry = self._entry(week, body)
        with self.lock:
            items = ts.load_manual(week, self.state)
            items.append({k: entry[k] for k in MANUAL_FIELDS})
            ts.save_manual(week, items, self.state)
            doc = self._read(week)
            if doc is not None:
                self._put_manual_line(doc, entry, None)
                self._write(week, doc)
        return self.week(week)

    def edit_manual(self, week: str, i: int, body: dict) -> dict:
        with self.lock:
            items = ts.load_manual(week, self.state)
            if not 0 <= i < len(items):
                raise BadRequest(f'нет ручной записи #{i}')
            old = items[i]
            entry = self._entry(week, body, old)
            items[i] = {k: entry[k] for k in MANUAL_FIELDS}
            ts.save_manual(week, items, self.state)
            doc = self._read(week)
            if doc is not None:
                self._put_manual_line(doc, entry, _manual_line(doc, old))
                self._write(week, doc)
        return self.week(week)

    def _put_manual_line(self, doc: dict, entry: dict, j: int | None) -> None:
        doc['lines'] = [ln for n, ln in enumerate(doc['lines']) if n != j and not (
            ln['sheet'] == entry['sheet'] and ln['day'] == entry['day'] and 'empty-day' in ln.get('flags', []))]
        doc['lines'].append({**asdict(ts.DraftLine(entry['sheet'], date.fromisoformat(entry['day']),
                             entry['key'], entry['seconds'], entry['comment'], 'manual')), 'day': entry['day']})
        doc['lines'].sort(key=lambda ln: (ln['day'], ln['sheet']))

    def remove_manual(self, week: str, i: int) -> dict:
        with self.lock:
            items = ts.load_manual(week, self.state)
            if not 0 <= i < len(items):
                raise BadRequest(f'нет ручной записи #{i}')
            m = items.pop(i)
            ts.save_manual(week, items, self.state)
            doc = self._read(week)
            if doc is not None:
                j = _manual_line(doc, m)
                if j is not None:
                    doc['lines'].pop(j)
                    self._write(week, doc)
        return self.week(week)

    def selection(self, week: str, sheets=None, days=None, pick=None) -> list | None:
        """Пары [табель, день]: sheets × days плюс явные pick «табель:день»; None — вся неделя."""
        start, end = ts.week_range(week)

        def day(v):
            try:
                d = date.fromisoformat(str(v))
            except ValueError:
                raise BadRequest(f'плохая дата {v!r}')
            if not start <= d <= end:
                raise BadRequest(f'{d} вне недели {week}')
            return d.isoformat()

        def sheet(v):
            if v not in self.rules.sheets:
                raise BadRequest(f'нет табеля {v!r}')
            return v

        for v in (sheets, days, pick):
            if v is not None and not isinstance(v, list):
                raise BadRequest('sheets, days и pick — списки')
        pairs = set()
        if sheets or days:
            all_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
            pairs = {(sheet(s), day(d)) for s in sheets or self.rules.sheets for d in days or all_days}
        for p in pick or []:
            s, _, d = str(p).partition(':')
            pairs.add((sheet(s), day(d)))
        return sorted([s, d] for s, d in pairs) if pairs else None

    def _plan(self, week: str, sel: list | None = None) -> tuple:
        try:
            lines = ts.load_draft(week, self.state)
        except FileNotFoundError:
            raise BadRequest('черновика нет — сначала «пересчитать»')
        pick = None if sel is None else {(s, date.fromisoformat(d)) for s, d in sel}
        actions, skipped = ts.plan_apply(lines, ts.load_sent(self.state), self._worklogs(week, fresh=True), pick=pick)
        row = lambda x: {'day': x.day.isoformat(), 'key': x.key, 'seconds': x.seconds, 'comment': x.comment,
                         'mirror_of': x.mirror_of}
        sheets = {}
        for name in sorted({x.sheet for x in actions} | {x.sheet for x, _ in skipped}):
            mine = [row(x) for x in actions if x.sheet == name]
            sheets[name] = {'actions': mine, 'total': sum(x['seconds'] for x in mine),
                            'skipped': [{**row(x), 'why': why} for x, why in skipped if x.sheet == name]}
        body = {'week': week, 'sheets': sheets}
        if sel is not None:
            body['selection'] = sel
        body['hash'] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return body, actions

    def plan(self, week: str, query: dict | None = None) -> dict:
        q = query or {}
        return self._plan(week, self.selection(week, q.get('sheet'), q.get('day'), q.get('pick')))[0]

    def apply(self, week: str, body: dict) -> dict:
        sel = self.selection(week, body.get('sheets'), body.get('days'), body.get('pick'))
        with self.write_lock:
            plan, actions = self._plan(week, sel)
            if not body.get('hash') or body['hash'] != plan['hash']:
                raise Conflict('план изменился с момента показа — ничего не отправлено, проверьте заново')
            results = ts.apply(actions, True, week, self.state, self.run)
            with self.lock:
                ts.mark_sent(week, results, self.state)
            self._worklogs(week, fresh=True)
        return {**self.week(week), 'results': [
            {'sheet': x.sheet, 'day': x.day.isoformat(), 'key': x.key, 'worklog_id': wid, 'error': err}
            for x, wid, err in results]}

    def change_sent(self, week: str, wid: int, body: dict | None) -> dict:
        body = body or {}
        if body.get('confirm') is not True:
            raise BadRequest('правка и удаление в Jira — только с confirm: true')
        key = str(body.get('key', '')).strip().upper()
        if not KEY.match(key):
            raise BadRequest(f'плохой ключ задачи {key!r}')
        sheet = body.get('sheet')
        if sheet is not None and sheet not in self.rules.sheets:
            raise BadRequest(f'нет табеля {sheet!r}')
        delete = body.get('delete') is True
        args = ['delete' if delete else 'update', key, str(wid)]
        if not delete:
            sec = body.get('seconds')
            if sec is not None:
                if not isinstance(sec, (int, float)) or isinstance(sec, bool) or not 0 < sec <= 24 * 3600:
                    raise BadRequest(f'плохие часы {sec!r}')
                args += ['--seconds', str(round(sec))]
            if 'comment' in body:
                args += ['--comment', str(body['comment'])]
            if len(args) == 3:
                raise BadRequest('нечего менять: нужны seconds или comment')

        def mine(field):
            return lambda r: r.get(field) == str(wid) and r.get('key', '').upper() == key and sheet in (None, r.get('sheet'))

        with self.write_lock:
            proc = self.run([str(ts.INTEGRATIONS / 'jira-worklog.sh'), *args, '--yes'], capture_output=True, text=True)
            if proc.returncode != 0:
                raise BadRequest((proc.stderr.strip().splitlines() or [f'код {proc.returncode}'])[-1])
            self._sync_sent(mine('worklog_id'), None if delete else body)
            if delete:
                self._unmark(week, mine('sent_id'))
            self._worklogs(week, fresh=True)
        return self.week(week)

    def _unmark(self, week: str, mine) -> None:
        with self.lock:
            doc = self._read(week)
            if doc is not None:
                for ln in doc['lines']:
                    if mine(ln):
                        ln['sent_id'] = ''
                self._write(week, doc)
            items = ts.load_manual(week, self.state)
            if any(mine(m) for m in items):
                ts.save_manual(week, [{k: v for k, v in m.items() if not (k == 'sent_id' and mine(m))} for m in items],
                               self.state)

    def _sync_sent(self, mine, change: dict | None) -> None:
        path = self.state / 'sent.jsonl'
        if not path.exists():
            return
        out = []
        for r in ts.load_sent(self.state):
            if mine(r):
                if change is None:
                    continue
                r = {**r, **{k: change[k] for k in ('seconds', 'comment') if k in change}}
                r['seconds'] = round(r['seconds'])
            out.append(json.dumps(r, ensure_ascii=False))
        path.write_text(''.join(line + '\n' for line in out))

    def index(self) -> bytes:
        theme = TOKENS.read_text().split('/* ---------- каркас')[0]
        html = INDEX.read_text().replace('/*TOKENS*/', theme).replace('__WEEK__', ts.current_week())
        return html.encode()


def _manual_line(doc: dict, m: dict) -> int | None:
    return next((j for j, ln in enumerate(doc['lines']) if ln.get('source') == 'manual' and not ln.get('sent_id')
                 and (ln['sheet'], ln['day'], ln['key'], ln['seconds']) ==
                 (m['sheet'], m['day'], m['key'], m['seconds'])), None)


def sync_manual(lines: list, manual: list, logs: dict, rules) -> list:
    # ручную запись могли добавить или удалить, пока пересчёт шёл без блокировки;
    # раскладку не подгоняем заново — день сверх нормы помечаем overflow
    sig = lambda sheet, day, key, sec, comment: (sheet, str(day), key, int(sec), (comment or '').strip())
    want = Counter(sig(m['sheet'], m['day'], m['key'], m['seconds'], m.get('comment')) for m in manual)
    out = []
    for ln in lines:
        if ln.source == 'manual':
            s = sig(ln.sheet, ln.day, ln.key, ln.seconds, ln.comment)
            if want[s]:
                want[s] -= 1
            elif not ln.sent_id:
                continue
        out.append(ln)
    for (sheet, day, key, sec, comment), n in want.items():
        out += [ts.DraftLine(sheet, date.fromisoformat(day), key, sec, comment, 'manual') for _ in range(n)]
    for sheet, day in {(s[0], date.fromisoformat(s[1])) for s, n in want.items() if n}:
        day_logs = logs.get(sheet)
        logged = sum(w.seconds for w in day_logs if w.day == day and rules.project_of(sheet, w.key)) \
            if isinstance(day_logs, list) else 0
        mine = [ln for ln in out if (ln.sheet, ln.day) == (sheet, day) and not ln.sent_id]
        if logged + sum(ln.seconds for ln in mine) > rules.sheets[sheet].day_hours * 3600:
            for ln in mine:
                if ln.source != 'manual' and ln.key and 'overflow' not in ln.flags:
                    ln.flags.append('overflow')
    return out


def merge_edits(lines: list, old: dict | None) -> list:
    if not old:
        return lines
    kept = [ts.DraftLine(**{**r, 'day': date.fromisoformat(r['day'])}) for r in old['lines']
            if r.get('edited') and r.get('source') != 'manual']
    drop = {(r['sheet'], r['day'], r['key']) for r in old.get('removed', [])}
    drop |= {(k.sheet, k.day.isoformat(), k.key) for k in kept}
    busy = {(k.sheet, k.day) for k in kept}
    fresh = [ln for ln in lines if ln.source == 'manual' or (ln.sheet, ln.day.isoformat(), ln.key) not in drop
             and not ('empty-day' in ln.flags and (ln.sheet, ln.day) in busy)]
    return sorted(fresh + kept, key=lambda ln: (ln.day, ln.sheet))


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False, default=_json_default).encode(),
                       'application/json; charset=utf-8')

        def _body(self) -> dict:
            n = int(self.headers.get('Content-Length') or 0)
            try:
                body = json.loads(self.rfile.read(n) or b'{}')
            except ValueError:
                raise BadRequest('тело запроса — не JSON')
            if not isinstance(body, dict):
                raise BadRequest('тело запроса — не объект')
            return body

        def _refused(self, write: bool) -> bool:
            port = self.server.server_address[1]
            hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
            origin = self.headers.get('Origin')
            if (self.headers.get('Host') or '').lower() not in hosts:
                self._json(403, {'error': 'чужой Host: сервер отвечает только на 127.0.0.1 и localhost'})
            elif origin is not None and origin.lower() not in {f'http://{h}' for h in hosts}:
                self._json(403, {'error': f'чужой Origin {origin}'})
            elif write and self.headers.get_content_type() != 'application/json':
                self._json(415, {'error': 'нужен Content-Type: application/json'})
            else:
                return False
            return True

        def _route(self, method: str):
            if method != 'GET' and self._refused(True):
                return
            m = ROUTE.match(self.path.split('?')[0])
            if m is None:
                return self._json(404, {'error': 'нет такого адреса'})
            action, idx = (m.group(2) or '').lower(), m.group(3)
            handlers = {
                ('GET', '', False): lambda w: app.week(w),
                ('POST', 'recompute', False): lambda w: app.recompute(w),
                ('PUT', 'draft', True): lambda w: app.edit_line(w, int(idx), self._body()),
                ('DELETE', 'draft', True): lambda w: app.edit_line(w, int(idx), None),
                ('POST', 'manual', False): lambda w: app.add_manual(w, self._body()),
                ('PUT', 'manual', True): lambda w: app.edit_manual(w, int(idx), self._body()),
                ('DELETE', 'manual', True): lambda w: app.remove_manual(w, int(idx)),
                ('GET', 'plan', False): lambda w: app.plan(w, parse_qs(self.path.partition('?')[2])),
                ('POST', 'apply', False): lambda w: app.apply(w, self._body()),
                ('PUT', 'sent', True): lambda w: app.change_sent(w, int(idx), {**self._body(), 'delete': False}),
                ('DELETE', 'sent', True): lambda w: app.change_sent(w, int(idx), {**self._body(), 'delete': True}),
            }
            fn = handlers.get((method, action, idx is not None))
            if fn is None:
                return self._json(404, {'error': 'нет такого адреса'})
            try:
                self._json(200, fn(norm_week(m.group(1))))
            except BadRequest as e:
                self._json(400, {'error': str(e)})
            except Conflict as e:
                self._json(409, {'error': str(e)})
            except Exception as e:
                self._json(500, {'error': str(e)})

        def do_GET(self):
            if self._refused(False):
                return
            path = self.path.split('?')[0]
            if path in ('/', '/index.html'):
                return self._send(200, app.index(), 'text/html; charset=utf-8')
            if path in STATIC:
                return self._send(200, STATIC[path].read_bytes(), 'text/javascript; charset=utf-8')
            self._route('GET')

        def do_POST(self):
            self._route('POST')

        def do_PUT(self):
            self._route('PUT')

        def do_DELETE(self):
            self._route('DELETE')

    return Handler


def make_server(app: App, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), make_handler(app))
