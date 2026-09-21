#!/usr/bin/env python3
try:
    from devflow.cli import main
except ModuleNotFoundError as exc:
    raise SystemExit(f'Missing dependency {exc.name}; run ./install.sh')

if __name__ == '__main__':
    raise SystemExit(main())
