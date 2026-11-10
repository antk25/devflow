"""pi as a phase harness: command line and result parsing."""


def build_command(body_file, tools, model_arg, message, options=('--no-session',)):
    return ['pi', '-p', *options, '--append-system-prompt', str(body_file), '--tools', ','.join(tools),
            *(['--model', model_arg] if model_arg else []), message]


def parse(stdout, stderr, exit_code):
    # pi -p prints plain text: no token, cost or session accounting to read.
    ok = exit_code == 0 and bool((stdout or '').strip())
    return {'status': 'ok' if ok else 'failed', 'tokens': None, 'cost': None, 'session_id': None}
