import json
import sys

import pytest

from devflow import cli, jev, workflow
from test_check import RUN, Resp, events, jev_answers, proj  # noqa: F401

RESEARCH = '''# r

## Problem
p

## Requirements
- Отчёт выгружается в CSV (ТЗ)
- Фильтр по дате (Jira: описание)
- Кнопка скачивания в шапке (Jira: комментарий Иван, 2026-09-20)
- Красивая иконка (Jira: описание; пожелание)

## Recommendation
r
'''


@pytest.fixture
def pp(proj, monkeypatch):
    monkeypatch.delenv('DEVFLOW_JEV_PLAN_THRESHOLD', raising=False)
    (proj['vault'] / 'research/x.md').write_text(RESEARCH)
    return proj


def answers(nouls, sent=None):
    def ok(req, timeout):
        body = json.loads(req.data)
        if sent is not None:
            sent.append(body)
        a = {}
        for n, v in enumerate(nouls, 1):
            a[f'addr_{n}'] = {'type': 'noul', 'noul': v}
            a[f'cov_{n}'] = {'type': 'choice', 'choice': 'covered' if v > 0.5 else 'not_covered'}
        return Resp(json.dumps({'model': 'typesafe/jev-1.13-x', 'answers': a}).encode())
    return ok


def run(p):
    return workflow.check(p['ctx'], p['db'], 'x', None, False, True)


def flagged(out):
    return [r['n'] for r in out['requirements'] if r['flagged']]


def test_default_threshold_flags(pp, monkeypatch):
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers([0.99, 0.9, 0.3]))
    out = run(pp)
    assert out['status'] == 'ok' and out['threshold'] == 0.95 and out['kind'] == 'plan'
    assert flagged(out) == [2, 3]
    assert all(r['source'] for r in out['requirements'])
    assert out['requirements'][2]['source'] == 'Jira: комментарий Иван, 2026-09-20'


def test_plan_threshold_env_independent_of_run(pp, monkeypatch):
    monkeypatch.setenv('DEVFLOW_JEV_PLAN_THRESHOLD', '0.7')
    monkeypatch.setenv('DEVFLOW_JEV_THRESHOLD', '0.7')
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers([0.99, 0.9, 0.3]))
    assert flagged(run(pp)) == [3]
    monkeypatch.delenv('DEVFLOW_JEV_PLAN_THRESHOLD')
    assert run(pp)['threshold'] == 0.95
    monkeypatch.setattr(jev.urllib.request, 'urlopen', jev_answers([0.9, 0.5, 0.1]))
    assert workflow.check(pp['ctx'], pp['db'], 'x', RUN, False)['threshold'] == 0.7


@pytest.mark.parametrize('case', ['no_research', 'no_section', 'empty', 'wishes', 'no_jev', 'no_plan'])
def test_skips_without_network(pp, case):
    research = pp['vault'] / 'research/x.md'
    if case == 'no_research':
        research.unlink()
    elif case == 'no_section':
        research.write_text('# r\n\n## Problem\np\n')
    elif case == 'empty':
        research.write_text('# r\n\n## Requirements\n- требований нет\n')
    elif case == 'wishes':
        research.write_text('# r\n\n## Requirements\n- иконка (ТЗ; пожелание)\n')
    elif case == 'no_jev':
        agents = pp['cwd'] / 'AGENTS.md'
        agents.write_text(agents.read_text().replace('jev: true\n', ''))
    else:
        (pp['vault'] / 'plans/x.md').unlink()
    out = run(pp)
    expected = {'no_research': 'нет требований', 'no_section': 'нет требований', 'empty': 'нет требований',
                'wishes': 'нет требований', 'no_jev': 'jev не включён в AGENTS.md', 'no_plan': 'нет плана'}
    assert out['status'] == 'skipped' and out['reason'] == expected[case]


def test_plan_over_limit_skips(pp):
    plan = pp['vault'] / 'plans/x.md'
    plan.write_text(plan.read_text() + 'слово ' * 12000)
    out = run(pp)
    assert out['status'] == 'skipped' and out['reason'].startswith('план больше лимита: ')
    assert int(out['reason'].split(': ')[1].split()[0]) > workflow.PLAN_LIMIT


def test_state_keys_full_plan_no_wish(pp, monkeypatch):
    sent = []
    plan = pp['vault'] / 'plans/x.md'
    plan.write_text(plan.read_text() + 'хвост плана\n')
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers([0.99, 0.99, 0.99], sent))
    run(pp)
    state = sent[0]['state']
    assert set(state) == {'ticket', 'plan'}
    assert state['plan'].endswith('хвост плана\n') and '## Risks' in state['plan']
    assert 'иконка' not in state['ticket'] and '(Jira: описание)' in state['ticket']
    assert set(sent[0]['questions']) == {'addr_1', 'cov_1', 'addr_2', 'cov_2', 'addr_3', 'cov_3'}


def test_secret_in_requirement_masked_in_questions(pp, monkeypatch):
    sent = []
    (pp['vault'] / 'research/x.md').write_text(RESEARCH.replace('Фильтр по дате', 'Доступ password=hunter2'))
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers([0.99, 0.99, 0.99], sent))
    run(pp)
    assert 'hunter2' not in json.dumps(sent[0], ensure_ascii=False)


def test_events_for_ok_and_skipped(pp, monkeypatch):
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers([0.99, 0.9, 0.3]))
    run(pp)
    (pp['vault'] / 'plans/x.md').unlink()
    run(pp)
    ok, skipped = events(pp['db'])
    assert ok['kind'] == 'plan' and ok['model'] == 'typesafe/jev-1.13-x' and ok['threshold'] == 0.95
    assert ok['noul'] == [0.99, 0.9, 0.3]
    assert skipped['kind'] == 'plan' and skipped['status'] == 'skipped' and skipped['noul'] == []


def test_cli_plan_flag(pp, monkeypatch, capsys):
    monkeypatch.setattr(jev.urllib.request, 'urlopen', answers([0.99, 0.9, 0.3]))
    monkeypatch.setattr(sys, 'argv', ['devflow', '--cwd', str(pp['cwd']), 'check', 'x', '--plan'])
    assert cli.main() == 0
    out = json.loads(capsys.readouterr().out)
    assert out['kind'] == 'plan' and flagged(out) == [2, 3]
