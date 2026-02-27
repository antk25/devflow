# Phase 5: E2E Testing

**CRITICAL:** After implementation, verify the feature works end-to-end using the E2E script.

```bash
# For each affected repository:
./scripts/e2e-check.sh backend /api/affected-endpoint
./scripts/e2e-check.sh frontend
```

The script handles:
- **Server availability check** — if server is not running, outputs how to start it (docker command, manual instructions) and exits with clear error
- **E2E test execution** — runs configured E2E command from projects.json
- **Custom endpoint testing** — for API repos, pass specific endpoint as second argument
- **Troubleshooting hints** — framework-specific debug instructions on failure

**Exit codes:** 0 = passed, 2 = server not running, 3 = tests failed.

If exit code is 2 (server not running), note in summary as "⏭️ E2E skipped" and continue.
If exit code is 3, attempt to fix and re-run (max 1 retry).

**Checkpoint:**
```bash
# If E2E passed:
./scripts/session-checkpoint.sh <branch> phase_6_commit result=success
# If E2E skipped (server not running):
./scripts/session-checkpoint.sh <branch> phase_6_commit result=skipped reason='server not running'
# If E2E failed but continuing:
./scripts/session-checkpoint.sh <branch> phase_6_commit result=warning reason='e2e tests failed'
```
