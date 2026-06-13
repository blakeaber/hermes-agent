# Phase 006-B: Rooben Verifier Surface

## Goal
Capture the Rooben LLM Verifier output (PASS/FAIL + criteria breakdown) into the event log whenever Hermes delegates work to Rooben, so Blake can review whether delegated work actually met its spec.

## Context
From Slack ts=1779051395: "I wish I could understand how Rooben Pro was deconstructing complex work into tasks — currently, I don't know when Hermes is doing it vs. Rooben. Also, I want to leverage Rooben's LLM Verifier output."

The `_dispatch_to_rooben()` function in `run_agent.py` is the integration point. This phase wraps that call to log both the dispatch and the verifier result.

## Dependencies
Phase 006-A must be Complete — this phase writes `rooben_dispatch` and `rooben_verification` events to the event log created in 006-A.

## Scope

### Files to Modify
- `run_agent.py` — wrap `_dispatch_to_rooben()` call site to emit `rooben_dispatch` event before the call and `rooben_verification` event after (with verifier result captured from the return value)
- `tools/workflow_events.py` — add `log_rooben_dispatch(workflow_id, spec, agent)` and `log_rooben_verification(workflow_id, passed, criteria, raw_output)` helpers

### Files to Create
- `tests/test_rooben_verifier_surface.py` — unit tests with mocked `_dispatch_to_rooben()` return value

### Explicitly Out of Scope
- Modifying Rooben internals or the verifier prompt — capture only, no changes to Rooben
- Re-running full task execution on `/workflow verify` — spec-only re-verification only

## Implementation Notes

**Resolve Q-6.1 first**: check what `_dispatch_to_rooben()` returns today. If it already returns a dict with `verifier_result`, use it. If it returns only the final answer text, you'll need to thread the verifier output back through (check `agentic-hub/rooben-planning/` for the return contract).

**Resolve Q-6.2**: confirm the Rooben verifier path. Expected: `~/Documents/agentic-hub/rooben-planning/verifier.py` or similar.

**rooben_dispatch event metadata:**
```json
{
  "agent": "rooben",
  "spec": "<the spec string passed to rooben>",
  "status": "dispatched"
}
```

**rooben_verification event metadata:**
```json
{
  "passed": true,
  "criteria": [
    {"label": "API returns 200", "met": true},
    {"label": "DB row written", "met": true}
  ],
  "raw_output": "<verifier LLM full response>"
}
```

**Re-verification for `/workflow verify`:** The `rooben_dispatch` event stores the spec. Phase 006-D calls `_dispatch_to_rooben(spec_only=True, spec=event['metadata']['spec'])` to re-run only the verifier step, not the full task.

## Acceptance Criteria
- [ ] After any turn that triggers `_dispatch_to_rooben()`, event log contains a `rooben_dispatch` event with `spec` in metadata
- [ ] After any Rooben turn, event log contains a `rooben_verification` event with `passed` (bool) and `criteria` (list) fields
- [ ] Re-verification callable via `EventLogger().rerun_verification(workflow_id)` without re-executing the task
- [ ] `pytest tests/test_rooben_verifier_surface.py -v` — all pass
  - Source: Slack ts=1779051395 (#product-feedback)

## Verification Steps
```bash
# 1. Resolve Q-6.1 first
grep -n "_dispatch_to_rooben" ~/Documents/hermes-agent/run_agent.py | head -10
# Note the line number of the call site and the return value

# 2. Run tests
pytest tests/test_rooben_verifier_surface.py -v
# Expected: all pass

# 3. Trigger a Rooben dispatch (manual)
# [manual] Ask Hermes something that routes to Rooben

# 4. Check event log
sqlite3 ~/.hermes/observability/events.db \
  "SELECT event_type, metadata FROM workflow_events WHERE event_type IN ('rooben_dispatch','rooben_verification') ORDER BY ts DESC LIMIT 2;"
# Expected: rooben_dispatch row + rooben_verification row with passed/criteria
```

## Status
Not started

## Bug Log
| # | Description | Status |
|---|-------------|--------|
