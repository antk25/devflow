from devflow.project import ROOT

IMPLEMENT = (ROOT / 'agents/implement.md').read_text()
CROSSREVIEW = (ROOT / 'agents/crossreview.md').read_text()
DRIVER = (ROOT / 'skills/devflow/SKILL.md').read_text()


def test_implement_lists_all_six_fork_stops():
    for stop in ('Вне плана', 'Контракт', 'Правка теста', '2 красные попытки', 'Необратимое действие', 'Бюджет'):
        assert f'**{stop}**' in IMPLEMENT, stop


def test_agents_read_decisions_journal():
    for text in (IMPLEMENT, CROSSREVIEW):
        assert 'notes/decisions-<slug>.md' in text


def test_crossreview_blocks_without_convergence():
    assert 'blocked: вопрос:' in CROSSREVIEW
    assert 'second review round' in CROSSREVIEW


def test_driver_writes_answer_to_journal():
    assert 'decisions-<slug>.md' in DRIVER and '`вопрос: …`' in DRIVER
