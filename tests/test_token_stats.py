import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/tokens/token-stats.py'


def test_html_report_renders(tmp_path):
    root = tmp_path / 'projects'
    (root / 'p').mkdir(parents=True)
    entries = [
        {'type': 'user', 'timestamp': '2026-09-22T09:00:00Z', 'cwd': '/home/u/projects/green', 'sessionId': 's1',
         'message': {'role': 'user', 'content': 'сделай SE-1'}},
        {'type': 'assistant', 'timestamp': '2026-09-22T09:01:00Z', 'cwd': '/home/u/projects/green', 'sessionId': 's1',
         'message': {'id': 'm1', 'model': 'claude-opus-5', 'usage': {'input_tokens': 10, 'output_tokens': 5}}},
        {'type': 'assistant', 'timestamp': '2026-09-22T09:02:00Z', 'cwd': '/home/u/projects/other', 'sessionId': 's2',
         'message': {'id': 'm2', 'model': 'claude-opus-5', 'usage': {'input_tokens': 1, 'output_tokens': 1}}},
    ]
    (root / 'p' / 's1.jsonl').write_text('\n'.join(json.dumps(e) for e in entries) + '\n')
    out = tmp_path / 'report.html'
    proc = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--html', str(out)],
                          env={**os.environ, 'HOME': str(tmp_path)}, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert 'SE-1' in out.read_text()


def test_opus_5_5_priced_at_4_per_million_input(tmp_path):
    root = tmp_path / 'projects'
    (root / 'p').mkdir(parents=True)
    entry = {'type': 'assistant', 'timestamp': '2026-10-01T09:00:00Z', 'cwd': '/home/u/projects/green',
             'sessionId': 's1',
             'message': {'id': 'm1', 'model': 'claude-opus-5-5',
                         'usage': {'input_tokens': 1_000_000, 'output_tokens': 0}}}
    (root / 'p' / 's1.jsonl').write_text(json.dumps(entry) + '\n')
    proc = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--by', 'model', '--json'],
                          env={**os.environ, 'HOME': str(tmp_path)}, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout)['rows']
    assert [(r['name'], r['cost']) for r in rows] == [('claude-opus-5-5', 4.0)]


def _run_one(tmp_path, entry, by, ledger=None):
    root = tmp_path / 'projects'
    (root / 'p').mkdir(parents=True)
    (root / 'p' / 's1.jsonl').write_text(json.dumps(entry) + '\n')
    if ledger:
        (tmp_path / '.claude' / 'devflow').mkdir(parents=True)
        (tmp_path / '.claude' / 'devflow' / 'task-ledger.jsonl').write_text(json.dumps(ledger) + '\n')
    proc = subprocess.run([sys.executable, str(SCRIPT), '--root', str(root), '--by', by, '--json'],
                          env={**os.environ, 'HOME': str(tmp_path)}, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)['rows']


def _entry(model, usage):
    return {'type': 'assistant', 'timestamp': '2026-11-10T09:00:00Z', 'cwd': '/home/u/projects/green',
            'sessionId': 's1', 'message': {'id': 'm1', 'model': model, 'usage': usage}}


def test_opus_5_5_cache_read_and_sonnet_5_5_priced_from_list(tmp_path):
    rows = _run_one(tmp_path, _entry('claude-opus-5-5', {'cache_read_input_tokens': 1_000_000}), 'model')
    assert round(rows[0]['cost'], 4) == 0.2
    rows = _run_one(tmp_path / 'b', _entry('claude-sonnet-5-5', {'input_tokens': 1_000_000}), 'model')
    assert round(rows[0]['cost'], 4) == 2.0


def test_print_session_phase_comes_from_ledger(tmp_path):
    ledger = {'ts': '2026-11-10T08:00:00+00:00', 'session': 's1', 'task': 'SE-1', 'phase': 'research'}
    rows = _run_one(tmp_path, _entry('claude-opus-5-5', {'input_tokens': 10}), 'phase', ledger)
    assert [r['name'] for r in rows] == ['research']
