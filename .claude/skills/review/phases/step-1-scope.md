# Step 1-2: Determine Scope & Gather Diff

## Step 1: Parse Arguments

| Input | Mode | Action |
|-------|------|--------|
| (none) or `staged` | Local | `git diff --cached` |
| `path/to/file` | Local | Read file(s) |
| `--pr 123` | GitHub PR | `gh pr diff 123` |
| `--mr 45` | GitLab MR | `glab mr diff 45` |
| `--branch name` | Branch | `git diff main...branch` |

## Step 2: Gather Code

### For Staged Changes
```bash
git diff --cached
```

### For Files/Directory
```bash
cat <file>
# For directory
find <dir> -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.php" \) | head -20
```

### For GitHub PR
```bash
gh pr view 123 --json title,body,author,files,additions,deletions
gh pr diff 123
gh pr view 123 --json comments
```

### For GitLab MR
```bash
glab mr view 45
glab mr diff 45
```

### For Branch
```bash
git fetch origin
git diff origin/main...origin/<branch>
git log origin/main...origin/<branch> --oneline
```

**Save the diff as `review_diff` — you will pass it to reviewers in Step 3.**
