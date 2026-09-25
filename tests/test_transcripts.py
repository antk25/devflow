import json
from datetime import datetime, timezone

from devflow.transcripts import human_messages, parse_ts, user_text

UTC = timezone.utc


def write(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(e) for e in entries) + '\n', encoding='utf-8')


def user(ts, content, **extra):
    return {'type': 'user', 'timestamp': ts, 'cwd': '/home/u/projects/green', 'sessionId': 's1',
            'message': {'role': 'user', 'content': content}, **extra}


def test_human_messages_skips_tool_results_sidechain_and_out_of_range(tmp_path):
    write(tmp_path / 'p' / 's1.jsonl', [
        user('2026-09-22T09:00:00Z', 'сделай SE-1'),
        user('2026-09-22T09:01:00Z', [{'type': 'tool_result', 'tool_use_id': 'x', 'content': 'ok'}]),
        user('2026-09-22T09:02:00Z', 'из подагента', isSidechain=True),
        user('2026-09-22T09:03:00Z', [{'type': 'text', 'text': '<system-reminder>r</system-reminder>дальше'}]),
        {'type': 'assistant', 'timestamp': '2026-09-22T09:04:00Z', 'message': {}},
        user('2026-09-30T09:00:00Z', 'за пределами'),
        'не json',
    ])
    msgs = list(human_messages(tmp_path, datetime(2026, 9, 21, tzinfo=UTC), datetime(2026, 9, 28, tzinfo=UTC)))
    assert [m.text for m in msgs] == ['сделай SE-1', 'дальше']
    assert msgs[0].ts == datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
    assert msgs[0].cwd == '/home/u/projects/green'
    assert msgs[0].session == 's1'


def test_parse_ts():
    assert parse_ts('2026-09-22T09:00:00.123Z') == datetime(2026, 9, 22, 9, 0, 0, 123000, tzinfo=UTC)
    assert parse_ts('') is None
    assert parse_ts('мусор') is None


def test_user_text_drops_system_reminders():
    assert user_text({'content': 'a<system-reminder>x</system-reminder>b'}) == 'a b'
