import io
import json
import socket
import urllib.error

import pytest

from devflow import jev


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fail(*a, **k):
    raise AssertionError('urlopen не должен вызываться')


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'dummy-key')


def test_no_key_skips_network(monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.setattr(jev.urllib.request, 'urlopen', fail)
    assert 'error' in jev.decide({}, jev.questions(['a']))


@pytest.mark.parametrize('exc', [
    socket.timeout('timed out'),
    urllib.error.URLError('down'),
    urllib.error.HTTPError(jev.URL, 500, 'err', {}, io.BytesIO(b'oops')),
    urllib.error.HTTPError(jev.URL, 403, 'Forbidden', {}, io.BytesIO(b'<html>blocked</html>')),
])
def test_errors_become_error(monkeypatch, key, exc):
    def boom(*a, **k):
        raise exc
    monkeypatch.setattr(jev.urllib.request, 'urlopen', boom)
    out = jev.decide({}, jev.questions(['a']))
    assert set(out) == {'error'} and out['error']
    assert 'dummy-key' not in out['error']


def test_http_codes_in_reason(monkeypatch, key):
    def boom(*a, **k):
        raise urllib.error.HTTPError(jev.URL, 403, 'Forbidden', {}, io.BytesIO(b'<html></html>'))
    monkeypatch.setattr(jev.urllib.request, 'urlopen', boom)
    assert '403' in jev.decide({}, [])['error']


def test_bad_json(monkeypatch, key):
    monkeypatch.setattr(jev.urllib.request, 'urlopen', lambda *a, **k: Resp(b'<html>'))
    assert 'error' in jev.decide({}, [])


def test_success_parses_answers(monkeypatch, key):
    sent = {}
    raw = {'model': 'typesafe/jev-1.13-20260917', 'answers': {
        'ev_0': {'type': 'noul', 'noul': 0.77},
        'st_0': {'type': 'choice', 'choice': 'verified', 'probabilities': {'verified': 0.72}, 'confidence': 0.58}},
        'usage': {'total_tokens': 1}}

    def ok(req, timeout):
        sent['body'] = json.loads(req.data)
        sent['timeout'] = timeout
        return Resp(json.dumps(raw).encode())
    monkeypatch.setattr(jev.urllib.request, 'urlopen', ok)
    out = jev.decide({'changelog': 'x'}, jev.questions(['crit']))
    assert out == {'model': raw['model'], 'answers': raw['answers']}
    assert sent['body']['model'] == 'typesafe/jev-1.13'
    assert set(sent['body']['questions']) == {'ev_0', 'st_0'}
    assert sent['timeout'] == 5


def test_questions_shape():
    q = jev.questions(['A', 'B'])
    assert [x['key'] for x in q] == ['ev_0', 'st_0', 'ev_1', 'st_1']
    assert q[1]['type'] == 'choice' and set(q[1]['criteria']) == {'verified', 'claimed', 'not_met'}
    assert q[0]['instructions'].endswith('Acceptance criterion: A')


def test_mask():
    token = 'A1b2' * 11
    out = jev.mask(f'ключ {token} в /srv/app-prod')
    assert token not in out and '[REDACTED]' in out
    assert '/srv/app-prod' in out
    assert jev.mask('password=hunter2') == 'password=[REDACTED]'


def test_mask_hides_auth_scheme_tokens():
    assert jev.mask('Authorization: Bearer abc123secret456') == 'Authorization: [REDACTED]'
    assert jev.mask('curl -H Bearer eyJhbGci1OiJIUzI1') == 'curl -H Bearer [REDACTED]'
    assert jev.mask('Bearer authentication is used') == 'Bearer authentication is used'


def test_mask_keeps_evidence_ids():
    text = ('tests/test_check.py::test_check_all_splits_sections_when_over_limit_2 passed, '
            'commit 7baee6a3f1c2d4e5b6a7980c1d2e3f4a5b6c7d8e')
    assert jev.mask(text) == text


def test_flag():
    assert jev.flag(0.5, 0.7)
    assert not jev.flag(0.9, 0.7)


def test_http_exception_becomes_error(monkeypatch, key):
    import http.client

    def boom(*a, **k):
        raise http.client.IncompleteRead(b'part')
    monkeypatch.setattr(jev.urllib.request, 'urlopen', boom)
    assert set(jev.decide({}, [])) == {'error'}
