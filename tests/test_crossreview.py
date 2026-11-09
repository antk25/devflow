"""Контракт протокола драйвера: runner намеренно не организует обзоры."""
from pathlib import Path

from devflow.documents import document

ROOT = Path(__file__).resolve().parents[1]


def body(name):
    return document(ROOT / 'agents' / f'{name}.md')['body']


def test_codex_failure_and_resume_contract():
    text = body('crossreview')
    for marker in ('codex login status', 'non-zero exit', 'usage limit', 'verdict block',
                   'Timeout Codex', 'SECOND_OPINION_NEEDED', 'second-opinion:',
                   'сохрани черновик', 'REVIEW_STALE'):
        assert marker in text
    assert text.index('## Step 2:') < text.index('## Step 3:')
    assert 'Save the list right away' in text
    assert 'git rev-parse <base> HEAD' in text
    assert 'git hash-object --stdin' in text
    assert 'не проверить' in text and 'Заметка: <absolute path>' in text


def test_independent_fallback_and_completed_only():
    second = body('second-opinion')
    assert 'Не получай и не читай черновик' in second
    assert 'REVIEW_STALE' in second
    driver = (ROOT / 'skills/devflow/SKILL.md').read_text()
    assert 'devflow agent run crossreview' in driver
    assert 'devflow agent run second-opinion' in driver
    assert 'Дословный ответ передаётся только новому crossreview' in driver
    assert 'не создаёт implement-run' in driver
    assert 'Run it once per task, not per step' in driver
    assert 'there is no `crossreview` launch yet' not in driver


def test_claude_models_and_agent_sequence_unchanged():
    cross = document(ROOT / 'agents/crossreview.md')['meta']
    second = document(ROOT / 'agents/second-opinion.md')['meta']
    assert (cross['model'], cross['effort']) == ('claude-opus-5-5', 'medium')
    assert (second['model'], second['effort']) == ('claude-fable-5-1', 'high')
    driver = (ROOT / 'skills/devflow/SKILL.md').read_text()
    assert 'Agent(subagent_type="crossreview")' in driver
    assert 'Agent(subagent_type="second-opinion")' in driver
    assert 'then a fresh `crossreview`' in driver


def test_legacy_draft_and_host_neutral_headers():
    text = body('crossreview')
    assert 'старый `## Claude (Opus 5.5)` также допустим' in text
    assert '## Собственное ревью (host=<host> model=<model>)' in text
    assert 'Старый черновик без этих полей тоже устарел' in text
