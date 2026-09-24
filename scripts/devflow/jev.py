import http.client
import json
import os
import re
import urllib.error
import urllib.request

URL = 'https://openrouter.ai/api/alpha/decisions'
MODEL = 'typesafe/jev-1.13'
PLACEHOLDER = '[REDACTED]'

EVIDENCE = ("The state holds the implementation changelog of a software task. Does the changelog contain concrete evidence "
            "that the acceptance criterion below is met: results of tests that cover it, a smoke or manual check with its "
            "outcome, observed behaviour or output, or measured numbers? A mere statement that it was done is not evidence.\n"
            "Acceptance criterion: {c}")
STATUS = "Classify the status of the acceptance criterion below according to the changelog in the state.\nAcceptance criterion: {c}"
CLASSES = {
    "verified": "The changelog contains concrete evidence that this criterion is met: test results covering it, a smoke or manual check with its outcome, observed behaviour or output, measured numbers.",
    "claimed": "The changelog says it is done or lists the relevant change, but gives no concrete verification evidence for this criterion.",
    "not_met": "The changelog says it is not done, deferred, pending (waits for deploy, prod smoke, review, a human step), failed, or does not mention it at all.",
}

ADDR = ("The state holds a customer ticket and the implementation plan written for it. Does the plan address the requirement "
        "below with a concrete step, decision or acceptance criterion? Mentioning it only as background or context does not count.\n"
        "Requirement: {r}")
COVER = "Classify how the plan in the state handles the ticket requirement below.\nRequirement: {r}"
PLAN_CLASSES = {
    "covered": "The plan contains a concrete step, decision or acceptance criterion that addresses the requirement.",
    "partial": "The plan addresses only part of the requirement, or only diagnoses it without deciding what to do.",
    "not_covered": "The plan does not address the requirement, mentions it only as background, or explicitly defers it.",
}

SECRETS = [
    re.compile(r"(?i)\b(sk|pk|rk|ghp|gho|github_pat|xox[abp]|glpat)[-_][A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)(bearer|token|password|passwd|pwd|secret|api[_-]?key|authorization)(\s*[:=]\s*)(?:(?:bearer|basic|token)\s+)?\S+"),
    re.compile(r"(?i)\b(bearer|basic)(\s+)(?=\S*\d)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@]+@"),
    re.compile(r"\b[A-Za-z0-9+=_]{40,}\b"),
]
# Commit SHAs and snake_case test names are the evidence the changelog must keep.
EVIDENCE_IDS = re.compile(r"[0-9a-f]+|[a-z0-9]+(?:_[a-z0-9]+)+")


def _long(m):
    s = m.group(0)
    return s if not re.search(r"\d", s) or EVIDENCE_IDS.fullmatch(s) else PLACEHOLDER


def mask(text: str) -> str:
    text = SECRETS[0].sub(PLACEHOLDER, text)
    text = SECRETS[1].sub(lambda m: m.group(1) + m.group(2) + PLACEHOLDER, text)
    text = SECRETS[2].sub(lambda m: m.group(1) + m.group(2) + PLACEHOLDER, text)
    text = SECRETS[3].sub(lambda m: m.group(1) + PLACEHOLDER + '@', text)
    return SECRETS[4].sub(_long, text)


def flag(noul: float, threshold: float) -> bool:
    return noul < threshold


def questions(criteria: list[str]) -> list[dict]:
    out = []
    for n, c in enumerate(map(mask, criteria)):
        out.append({'key': f'ev_{n}', 'type': 'noul', 'instructions': EVIDENCE.format(c=c)})
        out.append({'key': f'st_{n}', 'type': 'choice', 'instructions': STATUS.format(c=c), 'criteria': CLASSES})
    return out


def plan_questions(reqs: list[str]) -> list[dict]:
    out = []
    for n, r in enumerate(map(mask, reqs), 1):
        out.append({'key': f'addr_{n}', 'type': 'noul', 'instructions': ADDR.format(r=r)})
        out.append({'key': f'cov_{n}', 'type': 'choice', 'instructions': COVER.format(r=r), 'criteria': PLAN_CLASSES})
    return out


def decide(state: dict, questions: list[dict], timeout: float = 5) -> dict:
    key = os.environ.get('OPENROUTER_API_KEY')
    if not key:
        return {'error': 'OPENROUTER_API_KEY не задан'}
    payload = {q['key']: {k: v for k, v in q.items() if k != 'key'} for q in questions}
    body = json.dumps({'model': MODEL, 'state': state, 'questions': payload}).encode()
    req = urllib.request.Request(URL, data=body, method='POST', headers={
        'Authorization': 'Bearer ' + key,
        'Content-Type': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            out = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {'error': f'HTTP {e.code}'}
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
        return {'error': f'сеть: {type(e).__name__}'}
    except ValueError:
        return {'error': 'ответ не JSON'}
    if not isinstance(out, dict) or not isinstance(out.get('answers'), dict):
        return {'error': 'в ответе нет answers'}
    return {'model': out.get('model', MODEL), 'answers': out['answers']}
