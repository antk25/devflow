import json
import re
import threading
from dataclasses import asdict
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from devflow import timesheet as ts

HOST = '127.0.0.1'
SKILL_DIR = Path(__file__).resolve().parents[2] / 'skills'
INDEX = SKILL_DIR / 'timesheet' / 'index.html'
TOKENS = SKILL_DIR / 'page' / 'references' / 'tokens.css'
ROUTE = re.compile(r'^/api/week/((?:\d{4}-)?W\d{1,2})(/recompute)?$', re.I)


def norm_week(week: str) -> str:
    return week.upper() if '-W' in week.upper() else ts.current_week(ts.week_range(week)[0])


def _json_default(v):
    if isinstance(v, date):
        return v.isoformat()
    raise TypeError(type(v))


class App:
    def __init__(self, rules, state=ts.STATE_DIR, fetch=ts.fetch_worklogs, compute=None):
        self.rules, self.state, self.fetch = rules, state, fetch
        self.compute = compute or (lambda rules, logs, week: ts.draft(
            rules, logs, ts.load_activity(rules, week), ts.load_manual(week, state), week))
        self.cache, self.lock = {}, threading.Lock()

    def _worklogs(self, week: str, fresh: bool = False) -> dict:
        with self.lock:
            if fresh or week not in self.cache:
                self.cache[week] = self.fetch(self.rules, week)
            return self.cache[week]

    def week(self, week: str) -> dict:
        logs = self._worklogs(week)
        start, end = ts.week_range(week)
        path = self.state / f'draft-{week}.json'
        draft = json.loads(path.read_text()) if path.exists() else None
        sheets = {}
        for name, s in ts.summary(self.rules, logs, week).items():
            data = {k: v for k, v in s.items() if k != 'days'}
            if 'days' in s:
                data['days'] = [{'day': d, 'seconds': sec} for d, sec in s['days'].items()]
                data['worklogs'] = [asdict(w) for w in logs[name]]
            sheets[name] = data
        return {'week': week, 'start': start, 'end': end, 'current': ts.current_week(),
                'sheets': sheets, 'draft': draft}

    def recompute(self, week: str) -> dict:
        logs = self._worklogs(week, fresh=True)
        ts.save_draft(week, self.compute(self.rules, logs, week), self.state)
        return self.week(week)

    def index(self) -> bytes:
        html = INDEX.read_text().replace('/*TOKENS*/', TOKENS.read_text()).replace('__WEEK__', ts.current_week())
        return html.encode()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj, ensure_ascii=False, default=_json_default).encode(),
                       'application/json; charset=utf-8')

        def _route(self, post: bool):
            m = ROUTE.match(self.path.split('?')[0])
            if not m or bool(m.group(2)) != post:
                return self._json(404, {'error': 'нет такого адреса'})
            try:
                week = norm_week(m.group(1))
                self._json(200, app.recompute(week) if post else app.week(week))
            except Exception as e:
                self._json(500, {'error': str(e)})

        def do_GET(self):
            if self.path.split('?')[0] in ('/', '/index.html'):
                return self._send(200, app.index(), 'text/html; charset=utf-8')
            self._route(post=False)

        def do_POST(self):
            self._route(post=True)

    return Handler


def make_server(app: App, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((HOST, port), make_handler(app))
