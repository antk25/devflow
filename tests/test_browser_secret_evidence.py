import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'secret_evidence', Path(__file__).parents[1] / 'scripts/browser_secret_evidence.py')
secret_evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(secret_evidence)

VALUE = 'fake-Qx9vTe2LpR'


def setup(tmp_path, verdict_text):
    env_file = tmp_path / 'browser.env'
    env_file.write_text(f'OTHER=1\nPARITY_FAKE_SECRET={VALUE}\n')
    verdict = tmp_path / 'verdict.md'
    verdict.write_text(verdict_text)
    script = tmp_path / 'smoke.sh'
    script.write_text('type_text 2 "@env:PARITY_FAKE_SECRET"\n')
    return [str(env_file), str(verdict), str(script)]


def run(tmp_path, env_file, files, capsys, name='PARITY_FAKE_SECRET'):
    code = secret_evidence.main([env_file, name, *files])
    return code, capsys.readouterr().out


def test_pass_when_value_absent_and_never_printed(tmp_path, capsys):
    env_file, *files = setup(tmp_path, '| 1 | @env:PARITY_FAKE_SECRET введён | ✅ |\n')
    code, out = run(tmp_path, env_file, files, capsys)
    assert code == 0
    assert out.startswith('PASS: PARITY_FAKE_SECRET value absent in 2 artifact(s)')
    assert VALUE not in out


def test_fail_names_leaking_file_without_value(tmp_path, capsys):
    env_file, verdict, script = setup(tmp_path, f'typed {VALUE} into field\n')
    code, out = run(tmp_path, env_file, [verdict, script], capsys)
    assert code == 1
    assert out == f'FAIL: secret value present in {verdict}\n'


def test_missing_variable_or_artifact_is_not_a_pass(tmp_path, capsys):
    env_file, verdict, script = setup(tmp_path, 'ok\n')
    code, out = run(tmp_path, env_file, [verdict, script], capsys, name='ABSENT')
    assert code == 2 and out.startswith('FAIL: ABSENT is not defined')
    code, out = run(tmp_path, env_file, [verdict, str(tmp_path / 'nope.md')], capsys)
    assert code == 2 and 'artifact missing' in out
