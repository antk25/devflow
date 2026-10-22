"""Локальный стенд браузерной приёмки; никаких внешних запросов или сохранения данных."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == '/api/check':
            failed = parse_qs(url.query).get('fail') == ['1']
            body = json.dumps({'status': 'Ошибка' if failed else 'Готово'}, ensure_ascii=False).encode()
            self.send_response(500 if failed else 200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
        elif url.path == '/':
            body = (Path(__file__).parent / 'fixtures/parity-site/index.html').read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        else:
            self.send_error(404)
            return
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18765)
    args = parser.parse_args()
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
