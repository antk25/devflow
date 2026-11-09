import launch


def test_claude_driver_defaults_to_opus_high(monkeypatch):
    monkeypatch.delenv('DEVFLOW_MODEL', raising=False)
    monkeypatch.delenv('DEVFLOW_EFFORT', raising=False)
    argv = launch.claude_command('/bin/claude')
    assert ' '.join(argv) == '/bin/claude --model claude-opus-5-5 --effort high'


def test_claude_driver_env_and_arguments_override(monkeypatch):
    monkeypatch.setenv('DEVFLOW_MODEL', 'claude-fable-5-1')
    monkeypatch.setenv('DEVFLOW_EFFORT', 'low')
    assert launch.claude_command('c') == ['c', '--model', 'claude-fable-5-1', '--effort', 'low']
    assert launch.claude_command('c', 'm', 'medium') == ['c', '--model', 'm', '--effort', 'medium']
