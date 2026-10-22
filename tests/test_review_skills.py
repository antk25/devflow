from pathlib import Path

import pytest

from devflow import pi
from devflow.documents import document

ROOT = Path(__file__).resolve().parents[1]


def text(path):
    return (ROOT / path).read_text()


def test_review_independent_axes_and_output_contract():
    skill = text('skills/review/SKILL.md')
    for role, stem in [('review-standards', 'standards'), ('review-conformance', 'conformance')]:
        assert f'devflow agent run {role} --message-file <tmp>/{stem}.in.md > <tmp>/{stem}.out.json &' in skill
    for rule in ['чужие находки не добавлять', 'Не сливать и не переранжировать',
                 'Не сокращать цитаты ТЗ', 'худшее *внутри каждой* оси',
                 'ТЗ не найдено — ось', 'exit_code', 'warning', 'report']:
        assert rule in skill


@pytest.mark.parametrize('role', ['review-standards', 'review-conformance'])
def test_axis_tools_and_targets(role):
    body, tools = pi.agent_body(role)
    assert 'write' not in tools and 'edit' not in tools
    for target in ['git show <sha>', 'git diff <range>', 'git diff <base>...<branch>',
                   'git diff HEAD', 'untracked']:
        assert target in body
    assert "Never read the other axis's input/output or findings" in body


def test_conformance_requires_tz_not_research():
    body, _ = pi.agent_body('review-conformance')
    assert 'ТЗ не найдено — ось соответствия пропущена' in body
    assert 'Do not fall back to the research doc, the plan, or the Jira summary' in body
    assert 'quoted verbatim' in body


def test_xreview_portable_targets_and_failure_contract():
    skill = text('skills/xreview/SKILL.md')
    assert '/home/smg25/projects/resolventa/green' not in skill
    assert '--base main' not in skill
    for target in ['--base <base>', '--commit <sha>', '--uncommitted', 'git diff <range>']:
        assert target in skill
    for requirement in ['Base branch', 'AGENTS.md', 'cwd', 'codex login status',
                        'второе мнение не получено', 'Отсутствие вердикта', 'exit≠0',
                        '600 секунд', '</dev/null', 'не проверить', 'Не переключай рабочую ветку']:
        assert requirement in skill


def test_claude_keeps_two_agents_and_inherited_models():
    skill = text('skills/review/SKILL.md')
    assert 'Claude Code | Одним сообщением два вызова Agent' in skill
    for role in ['review-standards', 'review-conformance']:
        assert f'subagent_type: {role}' in skill
        meta = document(ROOT / f'agents/{role}.md')['meta']
        assert meta['model'] == 'inherit' and meta['effort'] == 'low'
    for name in ['review', 'xreview']:
        body = text(f'skills/{name}/SKILL.md')
        assert 'git status --porcelain=v1 --untracked-files=all' in body
        assert 'git diff HEAD --binary' in body
        assert 'содержимое untracked-файлов' in body


def test_verified_pi_prompts():
    for name in ['review', 'xreview']:
        assert document(ROOT / f'skills/{name}/SKILL.md')['meta']['pi'] is True
        assert f'`{name}` с аргументами: $ARGUMENTS' in text(f'pi/prompts/{name}.md')
