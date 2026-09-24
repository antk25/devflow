#!/usr/bin/env python3
import sys

if sys.argv[1:2] == ['guard']:
    from devflow.guard import main as guard_main
    raise SystemExit(guard_main())

try:
    from devflow.cli import main
except ModuleNotFoundError as exc:
    raise SystemExit(f'Missing dependency {exc.name}; run ./install.sh')

if __name__ == '__main__':
    raise SystemExit(main())
