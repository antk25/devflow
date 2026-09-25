import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "integrations" / "jira-worklog.sh"
ACCOUNTS = """
JIRA_ACCOUNTS="resolventa productsearch"
JIRA_DEFAULT_ACCOUNT=resolventa
JIRA_RESOLVENTA_BASE_URL=https://r.example
JIRA_RESOLVENTA_EMAIL=a@example.com
JIRA_RESOLVENTA_API_TOKEN=tok-secret-aaa
JIRA_RESOLVENTA_PROJECTS="DF GS"
JIRA_PRODUCTSEARCH_BASE_URL=https://p.example
JIRA_PRODUCTSEARCH_EMAIL=b@example.com
JIRA_PRODUCTSEARCH_API_TOKEN=tok-secret-bbb
JIRA_PRODUCTSEARCH_PROJECTS="SE"
"""

FAKE_CURL = r'''#!/usr/bin/env bash
cat > /dev/null
url="" method=GET
prev=""
for a in "$@"; do
  case "$prev" in --url) url="$a";; -X) method="$a";; esac
  prev="$a"
done
echo "$method $url" >> "$FAKE_LOG"
case "$method $url" in
  "GET "*/myself) body='{"accountId":"me-1"}'; code=200 ;;
  "GET "*/worklog/*) body="{\"id\":\"77\",\"author\":{\"accountId\":\"${FAKE_AUTHOR:-me-1}\"}}"; code=200 ;;
  *) body="${FAKE_BODY:-{\"id\":\"555\"\}}"; code="${FAKE_CODE:-201}" ;;
esac
printf '%s\n%s' "$body" "$code"
'''


@pytest.fixture
def run(tmp_path):
    (tmp_path / "curl").write_text(FAKE_CURL)
    (tmp_path / "curl").chmod(0o755)
    cfg = tmp_path / "config.env"
    cfg.write_text(ACCOUNTS)
    log = tmp_path / "curl.log"
    base = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "DEVFLOW_JIRA_CONFIG": str(cfg), "FAKE_LOG": str(log)}

    def go(*args, **env):
        result = subprocess.run(["bash", str(SCRIPT), *args], env={**base, **env},
                                capture_output=True, text=True)
        result.calls = log.read_text().splitlines() if log.exists() else []
        return result
    return go


def test_dry_run_prints_body_without_curl(run):
    r = run("add", "SE-12", "--day", "2026-09-22", "--seconds", "3600", "--comment", "поиск")
    assert r.returncode == 0, r.stderr
    assert r.calls == []
    lines = r.stdout.split("\n", 1)
    assert lines[0] == "POST /rest/api/2/issue/SE-12/worklog"
    assert json.loads(lines[1]) == {"started": "2026-09-22T09:00:00.000+0300",
                                    "timeSpentSeconds": 3600, "comment": "поиск"}
    assert "аккаунт productsearch" in r.stderr
    assert "tok-secret" not in r.stdout + r.stderr


def test_add_posts_and_prints_response(run):
    r = run("add", "DF-16", "--day", "2026-09-22", "--seconds", "1800", "--yes")
    assert r.returncode == 0, r.stderr
    assert r.calls == ["POST https://r.example/rest/api/2/issue/DF-16/worklog"]
    assert json.loads(r.stdout) == {"id": "555"}


def test_update_foreign_worklog_refused(run):
    r = run("update", "SE-12", "77", "--seconds", "600", "--yes", FAKE_AUTHOR="someone-else")
    assert r.returncode == 3
    assert not any(c.startswith("PUT") for c in r.calls)
    assert "не ваш" in r.stderr


def test_update_own_worklog_puts(run):
    r = run("update", "SE-12", "77", "--comment", "x", "--yes", FAKE_CODE="200")
    assert r.returncode == 0, r.stderr
    assert r.calls[-1] == "PUT https://p.example/rest/api/2/issue/SE-12/worklog/77"


def test_delete_foreign_refused(run):
    r = run("delete", "SE-12", "77", "--yes", FAKE_AUTHOR="someone-else")
    assert r.returncode == 3
    assert not any(c.startswith("DELETE") for c in r.calls)


def test_delete_own_empty_response(run):
    r = run("delete", "SE-12", "77", "--yes", FAKE_CODE="204", FAKE_BODY="")
    assert r.returncode == 0, r.stderr
    assert r.calls[-1] == "DELETE https://p.example/rest/api/2/issue/SE-12/worklog/77"


def test_error_response_fails_with_text(run):
    r = run("add", "SE-12", "--day", "2026-09-22", "--seconds", "60", "--yes",
            FAKE_CODE="400", FAKE_BODY='{"errorMessages":["Worklog must not be null"]}')
    assert r.returncode != 0
    assert "Worklog must not be null" in r.stderr


@pytest.mark.parametrize("args", [
    ("add", "SE-12", "--seconds", "60"),
    ("add", "SE-12", "--day", "2026-09-22", "--seconds", "0"),
    ("update", "SE-12", "77"),
    ("delete", "SE-12"),
    ("remove", "SE-12"),
])
def test_bad_args(run, args):
    r = run(*args)
    assert r.returncode == 2
    assert r.calls == []


def test_create_assignee_me_resolved_via_myself(tmp_path):
    (tmp_path / "curl").write_text('#!/usr/bin/env bash\ncat > /dev/null\necho "$*" >> "$FAKE_LOG"\necho \'{"accountId":"me-1"}\'\n')
    (tmp_path / "curl").chmod(0o755)
    (tmp_path / "config.env").write_text(ACCOUNTS)
    (tmp_path / "d.txt").write_text("x")
    create = SCRIPT.parent / "jira-create.sh"
    r = subprocess.run(["bash", str(create), "-P", "GS", "-s", "SE-1 t", "-d", str(tmp_path / "d.txt"), "-a", "me"],
                       env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
                            "DEVFLOW_JIRA_CONFIG": str(tmp_path / "config.env"), "FAKE_LOG": str(tmp_path / "curl.log")},
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["fields"]["assignee"] == {"accountId": "me-1"}
    [call] = (tmp_path / "curl.log").read_text().splitlines()
    assert "https://r.example/rest/api/2/myself" in call
