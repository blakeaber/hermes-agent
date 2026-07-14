# Phase 006-D: Slack `/workflow` Commands

## Goal
Add three Slack slash commands — `/workflow list`, `/workflow show <id>`, `/workflow verify <id>` — so Blake can inspect workflow history and trigger Rooben re-verification directly from Slack without leaving the conversation context.

## Context
From Slack ts=1779051463: "It is very challenging to inspect the inputs / outputs of requested work."
From Slack ts=1779051395: "I want to leverage Rooben's LLM Verifier output."

After 006-A and 006-B ship, the data exists but is only accessible via `sqlite3`. This phase surfaces it in Slack — the place Blake already works.

## Dependencies
- Phase 006-A must be Complete (event log exists with turn events)
- Phase 006-B must be Complete (`rooben_verification` events exist; `/workflow verify` needs them)

## Scope

### Files to Modify
- `hermes_cli/commands.py` — register `workflow` CommandDef with subcommands `list`, `show`, `verify`; add alias `wf`
- `tools/workflow_events.py` — add `format_workflow_summary()` and `format_workflow_detail()` (likely already stubbed in 006-A)
- `gateway/platforms/slack.py` — route `/workflow` slash commands to the command handler (follow existing `/plan` or similar pattern)

### Explicitly Out of Scope
- Web dashboard — deferred; Slack is sufficient for now
- Filtering/searching across workflows — `list` returns last 10 by recency
- Editing or annotating events from Slack

## Implementation Notes

**`/workflow list` output format:**
```
📋 Recent workflows (last 10):
• wf-a1b2c3 · 2026-05-19 10:15 · 3 events · ✅ complete
• wf-d4e5f6 · 2026-05-19 09:40 · 7 events · ✅ complete  [Rooben: PASS]
• wf-g7h8i9 · 2026-05-18 22:05 · 2 events · ⚠️ in_progress
```

**`/workflow show <id>` output format:**
```
🔍 Workflow wf-a1b2c3

Step 1 · turn_start · 10:14:55
  Input: "Create a Linear issue for implementing..."

Step 2 · rooben_dispatch · 10:15:02
  Agent: rooben | Status: complete

Step 3 · rooben_verification · 10:15:06
  Result: ✅ PASS (2/2 criteria met)

Step 4 · linear_issue_created · 10:15:08
  Issue: https://linear.app/...

Step 5 · turn_complete · 10:15:09
  Output: "Done — Linear issue created at..."
```

**`/workflow verify <id>` behavior:**
1. Look up the `rooben_dispatch` event for the workflow in the event log
2. Re-run `_dispatch_to_rooben(spec_only=True, spec=event['metadata']['spec'])`
3. Post result to Slack thread: PASS/FAIL with criteria breakdown
4. Append new `rooben_verification` event to the log

**Slash command registration:** Follow the pattern in `hermes_cli/commands.py`. The `workflow` command should be a `CommandDef` with `name='workflow'`, `aliases=['wf']`, and `subcommands=['list', 'show', 'verify']`.

**Gateway routing:** Slack sends `/workflow` as a message starting with `/`. Follow how existing commands like `/plan` or `/loop` are dispatched in `gateway/platforms/slack.py`.

## Acceptance Criteria
- [ ] `/workflow list` returns formatted list of ≤10 most recent workflows with IDs, timestamps, event counts, and statuses
- [ ] `/workflow show wf-{id}` returns full step-by-step event log in human-readable format
- [ ] `/workflow verify wf-{id}` triggers Rooben re-verification and posts PASS/FAIL with criteria breakdown as a thread reply
- [ ] `/wf list` alias works identically to `/workflow list`
- [ ] Unknown workflow ID returns: `❌ Workflow wf-{id} not found. Run /workflow list to see available workflows.`
- [ ] Commands work in any allowed Slack channel (not just DMs)
  - Source: Slack ts=1779051463, ts=1779051395 (#product-feedback)

## Verification Steps
```bash
# 1. Restart gateway after commands.py change
hermes gateway run --replace

# 2. [manual] Type /workflow list in Slack
# Expected: formatted list of recent workflows

# 3. [manual] Copy a workflow ID, type /workflow show wf-{id}
# Expected: full event log displayed

# 4. [manual] Type /workflow verify wf-{id} (a workflow that had Rooben dispatch)
# Expected: PASS or FAIL posted as thread reply

# 5. [manual] Type /workflow show wf-doesnotexist
# Expected: friendly error message

# 6. Run tests
pytest tests/test_workflow_commands.py -v
# Expected: all pass (test with mock event log)
```

## Status
Not started

## Bug Log
| # | Description | Status |
|---|-------------|--------|
