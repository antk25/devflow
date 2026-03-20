# Step 5: Debate Protocol

**Skip with `--no-debate` flag** — go directly to Step 6 with preliminary merged findings.
**Prerequisite:** At least 2 reviewers must have completed. If only 1 reviewer available, skip debate.

## 5a: Preliminary Merge

Collect all findings, deduplicate by file + problem, tag by source.

## 5b: Challenge Round

Each reviewer receives ALL findings from other reviewers and responds to EACH:
- **AGREE** — confirm the issue, optionally add evidence
- **CHALLENGE** — disagree, explain why it's not a real issue
- **ESCALATE** — issue is more serious than described

**Claude challenge:**
```
Task(
  description: "Challenge: review debate",
  prompt: "DEBATE MODE: You already reviewed this code. Now respond to other reviewers' findings.

## Your Original Findings
<Claude's findings>

## Other Reviewers' Findings
<Qwen + ChatGPT findings>

For EACH finding, respond: AGREE, CHALLENGE (+ why), or ESCALATE (+ why).
Format: ### [file:line] [title] → Verdict → Reasoning (1-2 sentences)",
  subagent_type: "Code Reviewer"
)
```

**Qwen + ChatGPT challenges** — run in parallel via MCP tools with same DEBATE MODE context.

## 5c: Defense Round

For each finding that received CHALLENGE, the original reviewer responds:
- **DEFEND** — provide additional evidence
- **WITHDRAW** — accept the challenge, retract finding

Run all defenses in parallel. **Skip if no findings were challenged.**

## 5d: Resolve Debate

| Scenario | Action |
|----------|--------|
| All AGREE / ESCALATE | Keep, highest confidence |
| CHALLENGE + DEFEND with evidence | Keep, high confidence |
| CHALLENGE + WITHDRAW | **Remove from report** |
| ESCALATE | Increase severity |
