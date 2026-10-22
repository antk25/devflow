"""Read-only Linux evidence for pinned chrome-devtools-mcp 1.10.1 sessions."""
import argparse
import json
import os
from pathlib import Path
import re


def processes(proc=Path('/proc')):
    result = {}
    for directory in proc.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            stat = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
            args = (directory / 'cmdline').read_bytes().decode().strip('\0').split('\0')
            try:
                env = (directory / 'environ').read_bytes().split(b'\0')
            except PermissionError:
                if any('chrome' in arg.lower() or 'node' in arg.lower() for arg in args):
                    raise
                env = []
            # Re-read identity: never combine data from different incarnations of a PID.
            again = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
            if stat[19] != again[19]:
                raise RuntimeError('PID changed during collection')
            result[int(directory.name)] = {
                'pid': int(directory.name), 'ppid': int(stat[1]),
                'starttime': stat[19], 'state': stat[0], 'args': args,
                'sessions': [item.split(b'=', 1)[1].decode() for item in env
                             if item.startswith(b'CHROME_DEVTOOLS_MCP_SESSION_ID=')],
            }
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            # Other users cannot be descendants of this unprivileged browser.
            if directory.stat().st_uid == os.getuid():
                raise
    return result


def owned(table, session, seeds=(), profiles=()):
    selected = {pid for pid, item in table.items()
                if session in item['sessions'] or
                any(arg == '--user-data-dir=' + profile
                    for profile in profiles for arg in item['args'])}
    selected.update(pid for pid, start in seeds
                    if pid in table and table[pid]['starttime'] == start)
    while True:
        expanded = selected | {pid for pid, item in table.items() if item['ppid'] in selected}
        if expanded == selected:
            return selected
        selected = expanded


def capture(session, pidfile, table):
    daemon = int(pidfile.read_text().strip())
    item = table[daemon]
    if session not in item['sessions'] or not any(arg.endswith('/daemon/daemon.js') for arg in item['args']):
        raise ValueError('metadata PID is not this session daemon')
    selected = owned(table, session, [(daemon, item['starttime'])])
    profiles = sorted({arg.split('=', 1)[1] for pid in selected
                       for arg in table[pid]['args'] if arg.startswith('--user-data-dir=')})
    if len(profiles) != 1:
        raise ValueError('expected one isolated Chrome profile after navigation')
    return {'session': session, 'pidfile': str(pidfile), 'profiles': profiles,
            'processes': [{key: table[pid][key] for key in ('pid', 'ppid', 'starttime', 'state')}
                          for pid in sorted(selected)]}


def verify(evidence, table):
    seeds = [(item['pid'], item['starttime']) for item in evidence['processes']]
    selected = owned(table, evidence['session'], seeds, evidence['profiles'])
    return [{'pid': pid, 'starttime': table[pid]['starttime'], 'state': table[pid]['state']}
            for pid in sorted(selected) if table[pid]['state'] != 'Z']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['capture', 'verify'])
    parser.add_argument('session')
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-f0-9-]+', args.session):
        parser.error('invalid session ID')
    table = processes()
    if args.operation == 'capture':
        runtime = Path(os.environ.get('XDG_RUNTIME_DIR', '/tmp'))
        suffix = '' if os.environ.get('XDG_RUNTIME_DIR') else '-' + str(os.getuid())
        pidfile = runtime / ('chrome-devtools-mcp-' + args.session + suffix) / 'daemon.pid'
        evidence = capture(args.session, pidfile, table)
        args.evidence.write_text(json.dumps(evidence, indent=2) + '\n')
        print(json.dumps(evidence))
    else:
        evidence = json.loads(args.evidence.read_text())
        if evidence['session'] != args.session:
            raise ValueError('session mismatch')
        survivors = verify(evidence, table)
        print(json.dumps({'session': args.session, 'profiles': evidence['profiles'],
                          'live_owned_processes': survivors}))
        return bool(survivors)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
