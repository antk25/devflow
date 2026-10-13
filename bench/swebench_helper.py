"""Dump SWE-bench instances to JSON. Runs only via `uv run --with swebench==<v>,datasets python -I <this file>`:
the `swebench`/`datasets` dependency stays out of the devflow package."""
import argparse
import json
import sys

FIELDS = ('instance_id', 'repo', 'version', 'base_commit', 'created_at', 'problem_statement', 'hints_text',
          'patch', 'test_patch', 'FAIL_TO_PASS', 'PASS_TO_PASS', 'image', 'eval_script', 'log_parser', 'eval_type')


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('instances')
    a.add_argument('--dataset', required=True)
    a.add_argument('--split', default='test')
    a.add_argument('--out', required=True)
    args = p.parse_args(argv)
    import swebench
    from datasets import load_dataset
    rows = load_dataset(args.dataset, split=args.split)
    instances = []
    for row in rows:
        item = {k: row.get(k) for k in FIELDS}
        for key in ('FAIL_TO_PASS', 'PASS_TO_PASS'):
            if isinstance(item[key], str):
                item[key] = json.loads(item[key])
        instances.append(item)
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump({'dataset': args.dataset, 'split': args.split, 'swebench': swebench.__version__,
                   'instances': instances}, fh, ensure_ascii=False)
    print(json.dumps({'count': len(instances), 'swebench': swebench.__version__}))


if __name__ == '__main__':
    sys.exit(main())
