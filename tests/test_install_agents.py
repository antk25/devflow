import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from devflow import policy
from devflow.project import ROOT

MARKER = policy.MARKER_KEY
EXAMPLE = policy.load(ROOT / 'model-policy.example.json')
GENERATED = sorted(f'{n}.md' for n in policy.agent_names(EXAMPLE))
LINKED = sorted(p.name for p in (ROOT / 'agents').glob('*.md') if p.stem not in policy.PHASES)


@pytest.fixture
def home(tmp_path):
    (tmp_path / 'home/.claude').mkdir(parents=True)
    # settings drift is checked by --check too; keep it green so only agent state decides the exit code
    text = (ROOT / 'settings.global.example.json').read_text().replace('__DEVFLOW_ROOT__', str(ROOT))
    (tmp_path / 'home/.claude/settings.json').write_text(text)
    return tmp_path / 'home'


def env(home):
    e = dict(os.environ)
    e.update(HOME=str(home), DEVFLOW_CLAUDE_DIR=str(home / '.claude'), DEVFLOW_BIN_DIR=str(home / 'bin'),
             DEVFLOW_INTEGRATIONS_DIR=str(home / 'integrations'), DEVFLOW_PI_DIR=str(home / 'pi'),
             DEVFLOW_MODEL_POLICY=str(home / 'model-policy.json'))
    e.pop('DEVFLOW_STATE_DIR', None)
    return e


def install(home, *args):
    return subprocess.run(['bash', str(ROOT / 'install.sh'), *args], env=env(home), capture_output=True, text=True)


def agents(home):
    return home / '.claude/agents'


def fallback_policy(home, effort='medium'):
    """Example policy whose implement/fallback effort differs from default, so `implement-fallback` is generated."""
    data = json.loads((ROOT / 'model-policy.example.json').read_text())
    data['claude']['implement']['fallback']['effort'] = effort
    (home / 'model-policy.json').write_text(json.dumps(data))
    return data


def test_install_generates_phase_agents_and_links_the_rest(home):
    assert not (home / 'model-policy.json').exists()
    r = install(home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'copy ' + str(home / 'model-policy.json') in r.stdout
    generated = sorted(p.name for p in agents(home).iterdir() if p.is_file() and not p.is_symlink())
    assert generated == GENERATED
    linked = sorted(p.name for p in agents(home).iterdir() if p.is_symlink())
    assert linked == LINKED
    text = (agents(home) / 'research-high.md').read_text()
    assert 'name: research-high\n' in text and 'model: claude-opus-5-5\n' in text and 'effort: high\n' in text
    assert text.split('---\n', 2)[2].startswith('<!-- ' + MARKER)
    assert (agents(home) / 'implement.md').read_text().count('model: claude-fable-5-1') == 1
    assert not list(agents(home).glob('*.tmp'))


def test_second_run_is_idempotent(home):
    assert install(home).returncode == 0
    before = {p.name: p.read_text() for p in agents(home).iterdir()}
    r = install(home)
    assert r.returncode == 0
    assert {p.name: p.read_text() for p in agents(home).iterdir()} == before
    assert 'generate ' not in r.stdout
    r = install(home, '--check')
    assert r.returncode == 0 and 'STALE' not in r.stdout, r.stdout


def test_old_symlink_to_our_source_is_replaced(home):
    agents(home).mkdir(parents=True)
    (agents(home) / 'plan.md').symlink_to(ROOT / 'agents/plan.md')
    r = install(home)
    assert r.returncode == 0, r.stderr
    assert not (agents(home) / 'plan.md').is_symlink() and MARKER in (agents(home) / 'plan.md').read_text()


def test_foreign_research_file_is_a_conflict(home):
    agents(home).mkdir(parents=True)
    (agents(home) / 'research.md').write_text('---\nname: research\n---\nmine\n')
    r = install(home)
    assert r.returncode == 1
    assert 'CONFLICT (not replacing): ' + str(agents(home) / 'research.md') in r.stderr
    assert (agents(home) / 'research.md').read_text().endswith('mine\n')
    assert not (agents(home) / 'plan.md').exists()


def test_foreign_fallback_file_is_a_conflict_when_policy_generates_it(home):
    fallback_policy(home)
    agents(home).mkdir(parents=True)
    (agents(home) / 'implement-fallback.md').write_text('---\nname: implement-fallback\n---\nmine\n')
    r = install(home)
    assert r.returncode == 1
    assert 'CONFLICT (not replacing): ' + str(agents(home) / 'implement-fallback.md') in r.stderr
    assert not (agents(home) / 'implement.md').exists()


def test_remove_deletes_generated_fallback_without_policy(home):
    fallback_policy(home)
    assert install(home).returncode == 0
    assert MARKER in (agents(home) / 'implement-fallback.md').read_text()
    (home / 'model-policy.json').unlink()
    r = install(home, '--remove')
    assert r.returncode == 0, r.stdout + r.stderr
    assert 'remove ' + str(agents(home) / 'implement-fallback.md') in r.stdout
    assert list(agents(home).iterdir()) == []


def test_check_reports_stale_after_policy_edit(home):
    assert install(home).returncode == 0
    p = home / 'model-policy.json'
    p.write_text(p.read_text().replace('"effort": "low"', '"effort": "medium"', 1))
    r = install(home, '--check')
    assert r.returncode == 1
    assert 'STALE agent implement' in r.stdout
    assert 'STALE agent plan' not in r.stdout
    assert 'ok ' + str(agents(home) / 'plan.md') in r.stdout and 'ok ' + str(agents(home) / 'implement.md') not in r.stdout
    assert 'ok ' + str(p) in r.stdout
    r = install(home)
    assert r.returncode == 0 and 'generate ' + str(agents(home) / 'implement.md') in r.stdout
    r = install(home, '--check')
    assert r.returncode == 0 and 'STALE' not in r.stdout, r.stdout


def test_check_reports_missing_agent(home):
    assert install(home).returncode == 0
    (agents(home) / 'plan-high.md').unlink()
    r = install(home, '--check')
    assert r.returncode == 1 and 'STALE agent plan-high' in r.stdout


def test_orphan_is_reported_by_check_and_removed_by_install(home):
    assert install(home).returncode == 0
    p = home / 'model-policy.json'
    data = json.loads(p.read_text())
    del data['claude']['plan']['high']
    p.write_text(json.dumps(data))
    r = install(home, '--check')
    assert r.returncode == 1 and 'ORPHAN agent plan-high' in r.stdout, r.stdout
    assert 'ok ' + str(agents(home) / 'plan-high.md') not in r.stdout
    r = install(home)
    assert r.returncode == 0 and 'remove ' + str(agents(home) / 'plan-high.md') in r.stdout, r.stdout
    assert not (agents(home) / 'plan-high.md').exists()
    r = install(home, '--check')
    assert r.returncode == 0 and 'ORPHAN' not in r.stdout, r.stdout


def test_install_keeps_unmarked_and_foreign_files(home):
    assert install(home).returncode == 0
    (agents(home) / 'plan-old.md').write_text('mine\n')
    (agents(home) / 'mine.md').write_text('keep\n')
    r = install(home)
    assert r.returncode == 0 and 'remove ' not in r.stdout, r.stdout
    assert (agents(home) / 'plan-old.md').read_text() == 'mine\n' and (agents(home) / 'mine.md').read_text() == 'keep\n'


def test_remove_deletes_only_generated_files(home):
    assert install(home).returncode == 0
    (agents(home) / 'mine.md').write_text('keep\n')
    r = install(home, '--remove')
    assert r.returncode == 0
    assert sorted(p.name for p in agents(home).iterdir()) == ['mine.md']


def test_check_flags_statusline_without_rate_limits_call(home):
    assert install(home).returncode == 0
    assert (home / 'bin/devflow-rate-limits').is_symlink()
    statusline = home / '.claude/statusline.sh'
    statusline.write_text('#!/usr/bin/env bash\ninput=$(cat)\n')
    r = install(home, '--check')
    assert r.returncode == 1 and 'MISS statusline call devflow-rate-limits' in r.stdout
    statusline.write_text('#!/usr/bin/env bash\ninput=$(cat)\necho "$input" | devflow-rate-limits\n')
    r = install(home, '--check')
    assert r.returncode == 0 and 'MISS statusline' not in r.stdout


def test_retro_skill_is_linked_and_skipped_for_pi(home):
    assert install(home).returncode == 0
    link = home / '.claude/skills/retro'
    assert link.is_symlink() and link.resolve() == (ROOT / 'skills/retro').resolve()
    r = install(home, '--check')
    assert r.returncode == 0 and 'skip pi retro' in r.stdout, r.stdout
    assert not (home / 'pi/skills/retro').exists()


def test_maintain_skill_is_linked_and_skipped_for_pi(home):
    assert install(home).returncode == 0
    link = home / '.claude/skills/maintain'
    assert link.is_symlink() and link.resolve() == (ROOT / 'skills/maintain').resolve()
    r = install(home, '--check')
    assert r.returncode == 0 and 'skip pi maintain' in r.stdout, r.stdout
    assert not (home / 'pi/skills/maintain').exists()


def pi_fields():
    from devflow.documents import document
    return {p.parent.name: document(p)['meta'].get('pi') for p in (ROOT / 'skills').glob('*/SKILL.md')}


def test_every_skill_declares_pi_as_true_or_a_reason():
    fields = pi_fields()
    assert fields
    for name, value in fields.items():
        assert value is True or (isinstance(value, str) and value.strip()), f'{name}: pi={value!r}'


def test_pi_prompts_match_skills_with_pi_true():
    linked = {name for name, value in pi_fields().items() if value is True}
    assert linked == {p.stem for p in (ROOT / 'pi/prompts').glob('*.md')}


def test_install_links_into_pi_exactly_the_skills_with_pi_true(home):
    assert install(home).returncode == 0
    fields = pi_fields()
    linked = {name for name, value in fields.items() if value is True}
    assert {p.name for p in (home / 'pi/skills').iterdir()} == linked
    assert {p.stem for p in (home / 'pi/prompts').iterdir()} == linked
    r = install(home, '--check')
    assert r.returncode == 0, r.stdout + r.stderr
    for name, value in fields.items():
        if value is not True:
            assert f'skip pi {name}: {value}\n' in r.stdout, r.stdout
    assert 'skip pi autoresearch: not verified for pi' in r.stdout


def test_review_skills_install_reinstall_remove(home):
    assert install(home).returncode == 0
    for name in ('review', 'xreview'):
        assert (home / 'pi/skills' / name).resolve() == ROOT / 'skills' / name
        assert (home / 'pi/prompts' / f'{name}.md').resolve() == ROOT / 'pi/prompts' / f'{name}.md'
    assert install(home).returncode == 0
    assert install(home, '--check').returncode == 0
    assert install(home, '--remove').returncode == 0
    for name in ('review', 'xreview'):
        assert not (home / 'pi/skills' / name).exists()
        assert not (home / 'pi/prompts' / f'{name}.md').exists()


def test_shared_rules_and_extension_install_reinstall_remove(home):
    assert install(home).returncode == 0
    rules = home / '.claude/devflow-instructions.md'
    original = rules.read_text()
    assert original == (ROOT / 'devflow-instructions.example.md').read_text()
    context = home / '.claude/CLAUDE.md'
    assert context.read_text().count(f'@{rules}') == 1
    extension = home / 'pi/extensions/devflow.ts'
    assert extension.is_symlink() and extension.resolve() == ROOT / 'pi/extensions/devflow.ts'
    assert install(home).returncode == 0
    assert context.read_text().count(f'@{rules}') == 1
    assert install(home, '--check').returncode == 0
    assert install(home, '--remove').returncode == 0
    assert not extension.exists()
    assert rules.read_text() == original
    assert context.read_text().count(f'@{rules}') == 1


def test_local_rules_preserved_with_backup_and_proposal(home):
    rules = home / '.claude/devflow-instructions.md'
    rules.write_text('Мои настройки\n')
    context = home / '.claude/CLAUDE.md'
    context.write_text('Мой контекст\n')
    policy = fallback_policy(home)
    result = install(home)
    assert result.returncode == 0, result.stderr
    assert 'REVIEW shared instructions' in result.stdout
    assert rules.read_text() == 'Мои настройки\n'
    backups = list(rules.parent.glob('devflow-instructions.md.*.bak'))
    assert len(backups) == 1 and backups[0].read_text() == rules.read_text()
    assert rules.with_name(rules.name + '.proposed').read_text() == (ROOT / 'devflow-instructions.example.md').read_text()
    assert context.read_text().startswith('Мой контекст\n')
    assert (home / '.claude/CLAUDE.md.devflow.bak').read_text() == 'Мой контекст\n'
    before = {p.name: p.read_bytes() for p in rules.parent.iterdir() if p.is_file()}
    assert install(home).returncode == 0
    assert {p.name: p.read_bytes() for p in rules.parent.iterdir() if p.is_file()} == before
    assert json.loads((home / 'model-policy.json').read_text()) == policy
    assert install(home, '--remove').returncode == 0
    assert rules.read_text() == 'Мои настройки\n'


def test_existing_relative_import_not_duplicated(home):
    context = home / '.claude/CLAUDE.md'
    context.write_text('@devflow-instructions.md\nМои правила\n')
    assert install(home).returncode == 0
    assert context.read_text() == '@devflow-instructions.md\nМои правила\n'


def test_empty_instructions_fail_preflight_without_installing(home):
    (home / '.claude/devflow-instructions.md').write_text('')
    result = install(home)
    assert result.returncode != 0
    assert not (home / 'pi/extensions/devflow.ts').exists()
    assert not (home / 'model-policy.json').exists()


def test_foreign_extension_fails_before_global_instructions_are_written(home):
    extension = home / 'pi/extensions/devflow.ts'
    extension.parent.mkdir(parents=True)
    extension.write_text('user extension')
    result = install(home)
    assert result.returncode != 0
    assert extension.read_text() == 'user extension'
    assert not (home / '.claude/devflow-instructions.md').exists()


def test_non_claude_harness_columns_get_no_agent():
    data = json.loads((ROOT / 'model-policy.example.json').read_text())
    data['claude']['research']['default'] = {'harness': 'codex', 'model': 'gpt-6', 'effort': 'medium'}
    data['claude']['plan']['high'] = {'harness': 'codex', 'model': 'gpt-6', 'effort': 'high'}
    data['claude']['implement']['default'] = {'harness': 'codex', 'model': 'gpt-6', 'effort': 'low'}
    names = policy.agent_names(data)
    assert 'research' not in names and 'research-high' in names
    assert 'plan' in names and 'plan-high' not in names
    assert 'implement' not in names and 'implement-fallback' in names
