# Phase 6: Commit Changes

After each task (or logical group), **in each affected repository:**

**Read git config from `PROJECT_CONFIG.git`:**
- `git.commit.format` — commit message format template
- `git.commit.body` — whether to include commit body
- `git.commit.coauthor` — whether to add Co-Authored-By footer
- `git.commit.language` — commit message language (en/ru)

```bash
# Switch to repo directory
cd /path/to/repo

# Stage changes
git add <specific files>

# Commit using project's git.commit config
git commit -m "<format per git.commit.format>"
```

**Format examples by config:**
- `"{ticket} {message}"` + body=false → `DEV-519 Add replace mode handler`
- `"feat({scope}): {message}"` + body=true, coauthor=true → multi-line with Co-Authored-By
- `"{message}"` + language=ru → `Добавить обработчик замены получателя`

**Checkpoint:**
```bash
./scripts/session-checkpoint.sh <branch> phase_6.5_test_reaction
```
