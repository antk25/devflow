"""Prove a browser.env secret value is absent from smoke artifacts without ever printing it."""
import argparse
from pathlib import Path
import sys


def secret_value(env_file, name):
    for line in Path(env_file).read_text().splitlines():
        key, sep, value = line.partition('=')
        if sep and key.strip() == name:
            return value.strip().strip('"').strip("'")
    raise LookupError(f'{name} is not defined in {env_file}')


def leaks(value, files):
    return [str(path) for path in files if value in Path(path).read_bytes().decode(errors='replace')]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    # Positional only: the pi guard denies option-style flags for unknown scripts.
    parser.add_argument('env_file')
    parser.add_argument('name')
    parser.add_argument('files', nargs='+')
    args = parser.parse_args(argv)
    try:
        value = secret_value(args.env_file, args.name)
    except (OSError, LookupError) as error:
        print(f'FAIL: {error}')
        return 2
    if len(value) < 4:
        print(f'FAIL: {args.name} value too short to be a meaningful probe')
        return 2
    missing = [path for path in args.files if not Path(path).is_file()]
    if missing:
        print('FAIL: artifact missing: ' + ', '.join(missing))
        return 2
    found = leaks(value, args.files)
    if found:
        print('FAIL: secret value present in ' + ', '.join(found))
        return 1
    print(f'PASS: {args.name} value absent in {len(args.files)} artifact(s); value not printed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
