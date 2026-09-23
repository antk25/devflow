import io
import json
import socket
import sys
import urllib.error

import pytest

from devflow import cli, documents, jev, workflow
from devflow.documents import context
from devflow.storage import connect

RUN = '11111111-1111-1111-1111-111111111111'
TOKEN = 'A1b2' * 11

PLAN = '''---
schema: 1
research_revision: {rev}
steps:
  - {{id: one, n: 1, blocked_by: []}}
  - {{id: old, n: 2, blocked_by: []}}
---

# Задача X — Plan

## Steps

### one: Первый
- **Goal:** g
- **Acceptance:**
  - критерий A
  - критерий B
  - критерий C

### old: Старый
- **Acceptance:** запустить pytest; всё зелёное

## Acceptance (overall)
- [ ] общий 1
- [ ] общий 2

## Risks
- не критерий
'''


def changelog(body_one='тесты зелёные, ключ ' + TOKEN, other='чужая секция'):
    return (f'# X — Changelog\n\n<!-- devflow-run: {RUN} -->\n## Шаг 1\n**Status:** done\n{body_one}\n'
            f'<!-- devflow-run: 22222222-2222-2222-2222-222222222222 -->\n## Шаг 2\n{other}\n')


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fail(*a, **k):
    raise AssertionError('urlopen не должен вызываться')


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv('DEVFLOW_STATE_DIR', str(tmp_path / 'state'))
    monkeypatch.setenv('OPENROUTER_API_KEY', 'dummy-key')
    monkeypatch.delenv('DEVFLOW_JEV_THRESHOLD', raising=False)
    monkeypatch.setattr(jev.urllib.request, 'urlopen', fail)
    vault, cwd = tmp_path / 'vault', tmp_path / 'proj'
    for d in ('plans', 'research', 'changelog'):
        (vault / d).mkdir(parents=True)
    cwd.mkdir()
    (cwd / 'AGENTS.md').write_text(f'---\nproject: p\nvault: {vault}\njev: true\n---\n')
    (vault / 'research/x.md').write_text('# r\n')
    rev = documents.document(vault / 'research/x.md')['revision']
    (vault / 'plans/x.md').write_text(PLAN.format(rev=rev))
    (vault / 'changelog/2026-09-23-x.md').write_text(changelog())
    ctx = context(cwd)
    db = connect(ctx, create=True)
    db.execute("INSERT INTO runs(id,slug,step_id,step_revision,plan_revision,research_revision,status) "
               "VALUES (?,?,?,?,?,?,?)", (RUN, 'x', 'one', 'r', 'r', 'r', 'running'))
    yield {'ctx': ctx, 'db': db, 'cwd': cwd, 'vault': vault}
    db.close()


def jev_answers(nouls, sent=None):
    replies = list(nouls) if nouls and isinstance(nouls[0], list) else [nouls]

    def ok(req, timeout):
        body = json.loads(req.data)
        if sent is not None:
            sent.append(body)
        values = replies[min(len(sent or [0]) - 1, len(replies) - 1)] if sent is not None else replies[0]
        answers = {}
        for n, v in enumerate(values):
            answers[f'ev_{n}'] = {'type': 'noul', 'noul': v}
            answers[f'st_{n}'] = {'type': 'choice', 'choice': 'verified' if v > 0.5 else 'claimed'}
        return Resp(json.dumps({'model': 'typesafe/jev-1.13-x', 'answers': answers}).encode())
    return ok


def flagged(out):
    return [c['criterion'] for c in out['criteria'] if c['flagged']]


def events(db):
    return [json.loads(r['data']) for r in db.execute("SELECT data FROM events WHERE action='check'")]


def test_flags_below_default_threshold(proj, monkeypatch):
    monkeypatch.setattr(jev.urllib.request, 'urlopen', jev_answers([0.9, 0.5, 0.1]))
    out = workflow.check(proj['ctx'], proj['db'], 'x', RUN, False)
    assert out['status'] == 'ok'
    assert flagged(out) == ['критерий B', 'критерий C']


def test_threshold_env_changes_flags(proj, monkeypatch):
    monkeypatch.setenv('DEVFLOW_JEV_THRESHOLD', '0.5')
    monkeypatch.setattr(jev.urllib.request, 'urlopen', jev_answers([0.9, 0.5, 0.1]))
    out = workflow.check(proj['ctx'], proj['db'], 'x', RUN, False)
    assert flagged(out) == ['критерий C'] and out['threshold'] == 0.5


def test_no_jev_flag_skips_without_network(proj):
    agents = proj['cwd'] / 'AGENTS.md'
    agents.write_text(agents.read_text().replace('jev: true\n', ''))
    out = workflow.check(proj['ctx'], proj['db'], 'x', RUN, False)
    assert out['status'] == 'skipped' and 'jev' in out['reason']


@pytest.mark.parametrize('exc', [None, socket.timeout('timed out'),
                                 urllib.error.HTTPError(jev.URL, 503, 'err', {}, io.BytesIO(b'x'))])
def test_failures_skip_with_reason_and_exit_zero(proj, monkeypatch, capsys, exc):
    if exc is None:
        monkeypatch.delenv('OPENROUTER_API_KEY')
    else:
        def boom(*a, **k):
            raise exc
        monkeypatch.setattr(jev.urllib.request, 'urlopen', boom)
    monkeypatch.setattr(sys, 'argv', ['devflow', '--cwd', str(proj['cwd']), 'check', 'x', '--run', RUN])
    assert cli.main() == 0
    printed = capsys.readouterr().out
    out = json.loads(printed)
    assert out['status'] == 'skipped' and out['reason']
    assert 'dummy-key' not in printed


def test_token_masked_and_run_sends_own_section(proj, monkeypatch):
    sent = []
    monkeypatch.setattr(jev.urllib.request, 'urlopen', jev_answers([0.9, 0.9, 0.9], sent))
    workflow.check(proj['ctx'], proj['db'], 'x', RUN, False)
    state = sent[0]['state']
    assert TOKEN not in state['changelog'] and '[REDACTED]' in state['changelog']
    assert 'чужая секция' not in state['changelog']
    text = json.dumps(sent[0]['questions'], ensure_ascii=False)
    assert 'критерий A' in text and 'общий 1' not in text and 'запустить pytest' not in text
    assert set(state) == {'task', 'changelog'}


def test_all_sends_overall_and_whole_changelog(proj, monkeypatch):
    sent = []
    monkeypatch.setattr(jev.urllib.request, 'urlopen', jev_answers([0.9, 0.2], sent))
    out = workflow.check(proj['ctx'], proj['db'], 'x', None, True)
    assert len(sent) == 1 and 'чужая секция' in sent[0]['state']['changelog']
    assert [c['criterion'] for c in out['criteria']] == ['общий 1', 'общий 2']
    assert flagged(out) == ['общий 2']


def test_one_line_acceptance_is_one_criterion():
    section = '### old: Старый\n- **Acceptance:** запустить pytest; всё зелёное\n- **Files:** a\n'
    assert documents.step_criteria(section) == ['запустить pytest; всё зелёное']
    assert documents.step_criteria('- **Acceptance:**\n  - a\n  - b\n- **Files:** x\n') == ['a', 'b']


def test_overall_criteria_stops_at_next_heading():
    assert documents.overall_criteria(PLAN) == ['общий 1', 'общий 2']


def test_oversized_run_section_skips(proj, monkeypatch):
    (proj['vault'] / 'changelog/2026-09-23-x.md').write_text(changelog(body_one='x' * 61000))
    out = workflow.check(proj['ctx'], proj['db'], 'x', RUN, False)
    assert out['status'] == 'skipped' and 'лимит' in out['reason']


def test_oversized_all_splits_and_takes_max(proj, monkeypatch):
    (proj['vault'] / 'changelog/2026-09-23-x.md').write_text(changelog(other='y ' * 31000))
    sent = []
    monkeypatch.setattr(jev.urllib.request, 'urlopen', jev_answers([[0.9, 0.1], [0.05, 0.3]], sent))
    out = workflow.check(proj['ctx'], proj['db'], 'x', None, True)
    assert len(sent) == 2
    assert [c['noul'] for c in out['criteria']] == [0.9, 0.3]
    assert out['criteria'][0]['choice'] == 'verified'
    assert flagged(out) == ['общий 2']


def test_events_written_and_state_untouched(proj, monkeypatch):
    db = proj['db']
    before = [list(map(tuple, db.execute(f'SELECT * FROM {t}'))) for t in ('approvals', 'steps', 'runs')]
    monkeypatch.delenv('OPENROUTER_API_KEY')
    workflow.check(proj['ctx'], db, 'x', RUN, False)
    monkeypatch.setenv('OPENROUTER_API_KEY', 'dummy-key')
    monkeypatch.setattr(jev.urllib.request, 'urlopen', jev_answers([0.9, 0.5, 0.1]))
    workflow.check(proj['ctx'], db, 'x', RUN, False)
    after = [list(map(tuple, db.execute(f'SELECT * FROM {t}'))) for t in ('approvals', 'steps', 'runs')]
    assert before == after
    ev = events(db)
    assert len(ev) == 2
    assert ev[0]['status'] == 'skipped' and ev[0]['threshold'] == 0.7 and ev[0]['noul'] == []
    assert ev[1]['model'] == 'typesafe/jev-1.13-x' and ev[1]['threshold'] == 0.7
    assert ev[1]['noul'] == [0.9, 0.5, 0.1]
    assert 'dummy-key' not in json.dumps(ev)


def test_run_section_shared_with_finish():
    assert workflow.run_section(changelog(), RUN).strip().startswith('## Шаг 1')
    assert workflow.run_section('нет маркера', RUN) is None


def test_overall_criteria_joins_wrapped_and_nested_items():
    body = ('## Acceptance (overall)\n- [ ] Тест с подменой Jev: … → в JSON помечены\n'
            '      второй и третий. Тесты CLI не обращаются к сети.\n'
            '- [ ] Без ключа → `skipped`:\n  - при таймауте;\n  - при HTTP 5xx.\n')
    assert documents.overall_criteria(body) == [
        'Тест с подменой Jev: … → в JSON помечены второй и третий. Тесты CLI не обращаются к сети.',
        'Без ключа → `skipped`: при таймауте; при HTTP 5xx.']


def test_step_criteria_joins_wrapped_sub_item():
    section = '- **Acceptance:**\n  - первый\n    продолжение\n  - второй\n- **Files:** x\n'
    assert documents.step_criteria(section) == ['первый продолжение', 'второй']


def test_step_criteria_one_line_old_style():
    assert documents.step_criteria('- **Acceptance:** одна строка; и ещё\n') == ['одна строка; и ещё']


def test_validate_omits_step_text(proj):
    args = cli.parser().parse_args(['--cwd', str(proj['cwd']), 'validate', 'x'])
    out = cli.execute(args)
    assert out['steps'] and all('text' not in s for s in out['steps'])
