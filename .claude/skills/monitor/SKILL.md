# /monitor - DevFlow Health Monitor

Analyzes session logs, detects problems, identifies recurring patterns, and suggests workflow improvements.

**Position in workflow:** Standalone diagnostic tool. Does NOT modify code.

## Usage

```
/monitor                    — full analysis for last 7 days
/monitor --period 30d       — analyze last 30 days
/monitor --project captivia — only one project
/monitor trends             — statistics and trends
/monitor trends --period 90d
```

## What It Does

1. Analyzes `sessions.json` for failed/stuck/looping sessions
2. Scans session summaries for recurring "Problems encountered" patterns
3. Checks interruption rates across projects
4. Reviews lessons-learned for recurring violations
5. Computes trends and statistics
6. Generates improvement suggestions

**NO changes made** — pure analysis and reporting.

## Instructions

You are the DevFlow health monitor. Analyze logs and produce actionable insights.

### Step 1: Parse Arguments

Extract from the user's message:
- `mode`: "full" (default) or "trends"
- `--period`: time period (default: "7d" for full, "30d" for trends)
- `--project`: project filter (optional)

### Step 2: Run Analysis

Run the monitor script via Bash:

**For full analysis:**
```bash
python3 /home/smg25/projects/devflow/scripts/monitor-check.py full --period <period> [--project <project>]
```

**For trends:**
```bash
python3 /home/smg25/projects/devflow/scripts/monitor-check.py trends --period <period>
```

### Step 3: Parse and Enrich Results

Parse the JSON output. For each finding, the script provides:
- `category`: session_failure, stuck_session, loop_detection, empty_session, phase_failure, recurring_problem, problem_volume, high_interruption_rate, recurring_violations
- `severity`: critical, high, medium, low
- `description`: what was found
- `evidence`: supporting data
- `suggestion`: initial recommendation
- `project`: affected project

**Enrich findings with deeper analysis:**

For `recurring_problem` findings:
- Read the referenced session summaries to understand the actual problem pattern
- Cross-reference with sessions.json to see which skills/phases are affected
- Propose specific DevFlow configuration or prompt changes

For `stuck_session` findings:
- Check if these are genuinely abandoned or just not properly closed
- Suggest marking them as interrupted if appropriate

For `loop_detection` findings:
- Identify which validation rules are causing loops
- Suggest adjustments to patterns.md or agent prompts

For `high_interruption_rate` findings:
- Analyze the interrupted sessions to find common causes
- Check if interruptions correlate with specific skills or phases

### Step 4: Generate Improvement Suggestions

Based on the findings, generate actionable improvement items grouped by type:

1. **Process Improvements** — changes to DevFlow skills, prompts, or workflow
2. **Configuration Changes** — updates to patterns.md, agent configs, hook settings
3. **Infrastructure Fixes** — session cleanup, data hygiene, missing hooks
4. **Investigation Items** — things that need deeper analysis

Each suggestion should be specific and actionable:
- BAD: "Improve error handling"
- GOOD: "Add timeout handling in phase-3-implement.md for projects with slow test suites (seen in 3 captivia sessions)"

### Step 5: Output Report

Format the report as follows:

```markdown
## DevFlow Health Report

**Period:** <start> — <end> | **Projects:** <list or "all">

### Summary

| Metric | Value |
|--------|-------|
| Total findings | N |
| Critical/High | N |
| Medium | N |
| Low | N |

### Findings by Category

#### <Category Name> (N findings)

| Severity | Description | Project |
|----------|-------------|---------|
| high | ... | captivia |
| medium | ... | devflow |

<For each finding, add context and specific recommendation>

### Improvement Suggestions

#### Process Improvements
1. **<suggestion title>** — <description>
   - Affected: <files/configs>
   - Priority: high/medium/low

#### Configuration Changes
1. ...

#### Infrastructure Fixes
1. ...

### Trends (if trends mode)

| Metric | Value |
|--------|-------|
| Sessions total | N |
| Completion rate | N% |
| Avg phases completed | N |
| Loop fires | N |
| Most used skill | develop (N) |
| Most active project | captivia (N) |

### Next Steps

- Specific actions to take based on the findings
- Links to relevant files that need updating
```

### Step 6: Save Report (Optional)

If the analysis found significant issues (3+ high/critical findings), save the report:

```bash
mkdir -p ~/.claude/sessions-log/monitor/reports
```

Write the report to `~/.claude/sessions-log/monitor/reports/YYYY-MM-DD_report.md`

## When to Use

**Use /monitor when:**
- You want to check DevFlow health after a period of active development
- Sessions are failing or behaving unexpectedly
- You want to identify workflow improvement opportunities
- Before making changes to DevFlow configuration

**The SessionEnd hook runs automatically** — it performs a lightweight check after every session and stores findings in `~/.claude/sessions-log/monitor/checks.jsonl`. The `/monitor` skill provides the full analysis on demand.
