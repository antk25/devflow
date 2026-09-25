import os
import subprocess
from pathlib import Path

import pytest

INTEGRATIONS = Path(__file__).resolve().parent.parent / "integrations"
LIB = INTEGRATIONS / "jira-accounts.sh"
TOKEN_A = "tok-secret-aaa"
TOKEN_B = "tok-secret-bbb"

ACCOUNTS = f"""
JIRA_ACCOUNTS="resolventa productsearch"
JIRA_DEFAULT_ACCOUNT=resolventa
JIRA_RESOLVENTA_BASE_URL=https://r.example
JIRA_RESOLVENTA_EMAIL=a@example.com
JIRA_RESOLVENTA_API_TOKEN={TOKEN_A}
JIRA_RESOLVENTA_PROJECTS="DF OPS"
JIRA_PRODUCTSEARCH_BASE_URL=https://p.example
JIRA_PRODUCTSEARCH_EMAIL=b@example.com
JIRA_PRODUCTSEARCH_API_TOKEN={TOKEN_B}
JIRA_PRODUCTSEARCH_PROJECTS="SE"
"""


@pytest.fixture
def env(tmp_path):
    log = tmp_path / "curl.log"
    curl = tmp_path / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        f'{{ printf "ARGV:%s\\n" "$@"; printf "STDIN:"; cat; }} >> "{log}"\n'
        'code="${FAKE_CODE:-200}"\n'
        'for a in "$@"; do case "$a" in *http_code*) printf \'{"displayName":"Tester","key":"X-1"}\\n%s\' "$code"; exit 0;; esac; done\n'
        'printf \'{"key":"X-1"}\'\n'
    )
    curl.chmod(0o755)
    cfg = tmp_path / "config.env"
    cfg.write_text(ACCOUNTS)
    base = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "DEVFLOW_JIRA_CONFIG": str(cfg)}

    def lib(snippet, extra_env=None):
        script = f'source "{LIB}"; jira_accounts_load; {snippet}'
        return subprocess.run(["bash", "-c", script], env={**base, **(extra_env or {})},
                              capture_output=True, text=True)

    def run(*args, extra_env=None):
        return subprocess.run(["bash", *map(str, args)], env={**base, **(extra_env or {})},
                              capture_output=True, text=True)

    lib.cfg, lib.log, lib.run = cfg, log, run
    return lib


@pytest.mark.parametrize("ref,expected", [
    ("SE-12", "productsearch"), ("SE", "productsearch"), ("se-3", "productsearch"),
    ("DF-17", "resolventa"), ("OPS", "resolventa"),
    ("productsearch", "productsearch"), ("XYZ-1", "resolventa"),
])
def test_resolve(env, ref, expected):
    result = env(f"jira_account_resolve {ref}")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


def test_no_default_refuses(env):
    env.cfg.write_text(ACCOUNTS.replace("JIRA_DEFAULT_ACCOUNT=resolventa", ""))
    result = env("jira_account_resolve XYZ-1")
    assert result.returncode == 2
    assert "ключ XYZ не принадлежит ни одному аккаунту" in result.stderr


def test_key_conflict_names_both(env):
    env.cfg.write_text(ACCOUNTS.replace('PROJECTS="SE"', 'PROJECTS="SE DF"'))
    result = env("true")
    assert result.returncode == 2
    assert "ключ DF у аккаунтов resolventa и productsearch" in result.stderr


def test_missing_field_named(env):
    env.cfg.write_text(ACCOUNTS.replace("JIRA_PRODUCTSEARCH_EMAIL=b@example.com", ""))
    result = env("true")
    assert result.returncode == 2
    assert "аккаунт productsearch: нет поля JIRA_PRODUCTSEARCH_EMAIL" in result.stderr
    assert TOKEN_B not in result.stderr


def test_unknown_default_refused(env):
    env.cfg.write_text(ACCOUNTS.replace("DEFAULT_ACCOUNT=resolventa", "DEFAULT_ACCOUNT=nope"))
    assert env("true").returncode == 2


def test_legacy_pairs_synthesized(env):
    env.cfg.write_text(
        f"JIRA_BASE_URL=https://r.example\nJIRA_EMAIL=a@example.com\nJIRA_API_TOKEN={TOKEN_A}\n"
        f"JIRA_PS_BASE_URL=https://p.example\nJIRA_PS_EMAIL=b@example.com\nJIRA_PS_API_TOKEN={TOKEN_B}\n"
    )
    result = env("jira_accounts_list; jira_account_resolve SE-1; jira_account_resolve DF-1;"
                 " jira_account_field productsearch BASE_URL")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["resolventa", "productsearch", "productsearch", "resolventa",
                                     "https://p.example"]


def test_field_refuses_token(env):
    result = env("jira_account_field resolventa API_TOKEN")
    assert result.returncode == 2
    assert TOKEN_A not in result.stdout + result.stderr


def test_issue_script_token_only_in_stdin(env):
    result = env.run(INTEGRATIONS / "jira-issue.sh", "SE-5")
    assert result.returncode == 0, result.stderr
    log = env.log.read_text()
    argv = "\n".join(line for line in log.splitlines() if line.startswith("ARGV:"))
    assert "ARGV:https://p.example/rest/api/3/issue/SE-5?expand=renderedFields" in argv
    assert TOKEN_B not in argv
    assert f'user = "b@example.com:{TOKEN_B}"' in log
    assert TOKEN_B not in result.stdout + result.stderr


def test_raw_script_resolves_by_key_prefix(env):
    result = env.run(INTEGRATIONS / "jira-raw.sh", "DF-7/changelog", ".key")
    assert result.returncode == 0, result.stderr
    assert "ARGV:https://r.example/rest/api/3/issue/DF-7/changelog" in env.log.read_text()
    assert TOKEN_A not in result.stdout + result.stderr


def test_check_ok(env):
    result = env.run(LIB, "check")
    assert result.returncode == 0, result.stderr
    assert result.stdout.count("Tester") == 2
    assert TOKEN_A not in result.stdout and TOKEN_B not in result.stdout


def test_check_401(env):
    result = env.run(LIB, "check", extra_env={"FAKE_CODE": "401"})
    assert result.returncode == 1
    assert "нет доступа (HTTP 401)" in result.stdout
    assert TOKEN_A not in result.stdout + result.stderr


def _argv(env):
    return [line for line in env.log.read_text().splitlines() if line.startswith("ARGV:")]


@pytest.mark.parametrize("args,base", [
    (["--account", "productsearch", "project = SE"], "https://p.example"),
    (["project = DF"], "https://r.example"),
])
def test_jql_account_flag(env, args, base):
    result = env.run(INTEGRATIONS / "jira-jql.sh", *args)
    assert result.returncode == 0, result.stderr
    assert f"ARGV:{base}/rest/api/3/search/jql" in _argv(env)
    assert TOKEN_A not in result.stdout + result.stderr and TOKEN_B not in result.stdout + result.stderr


def test_search_account_flag(env):
    result = env.run(INTEGRATIONS / "jira-search.sh", "--account", "productsearch", "project = SE")
    assert result.returncode == 0, result.stderr
    assert "ARGV:https://p.example/rest/api/3/search/jql" in _argv(env)


def test_comment_resolves_by_key(env):
    result = env.run(INTEGRATIONS / "jira-comment.sh", "SE-9", "42")
    assert result.returncode == 0, result.stderr
    assert "ARGV:https://p.example/rest/api/3/issue/SE-9/comment/42?expand=renderedBody" in _argv(env)


def test_attachment_by_key(env, tmp_path):
    result = env.run(INTEGRATIONS / "jira-attachment.sh", "--account", "SE-1", "77",
                     extra_env={"JIRA_ATTACH_DIR": str(tmp_path / "att")})
    assert result.returncode == 0, result.stderr
    assert "ARGV:https://p.example/rest/api/3/attachment/content/77" in _argv(env)


def test_create_resolves_project(env, tmp_path):
    result = env.run(INTEGRATIONS / "jira-create.sh", "-P", "COM", "--types")
    assert "аккаунт resolventa" in result.stderr
    assert "ARGV:https://r.example/rest/api/2/issue/createmeta/COM/issuetypes" in _argv(env)
    desc = tmp_path / "d.txt"
    desc.write_text("x")
    dry = env.run(INTEGRATIONS / "jira-create.sh", "-P", "SE", "-s", "t", "-d", desc)
    assert dry.returncode == 0, dry.stderr
    assert "аккаунт productsearch" in dry.stderr and "DRY RUN" in dry.stderr
    assert TOKEN_B not in dry.stdout + dry.stderr
