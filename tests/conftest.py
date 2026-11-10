import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    from devflow import transcripts
    path = tmp_path / 'task-ledger.jsonl'
    monkeypatch.setattr(transcripts, 'LEDGER', path)
    return path
