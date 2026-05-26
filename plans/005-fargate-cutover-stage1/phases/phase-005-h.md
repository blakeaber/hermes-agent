# Phase 005-H: Document + open Plan 006 / Plan 008 carry-forwards

## Goal
Mark Plan 005 Complete; record cutover metrics for future reference; ensure Plan 008 (MCPGateway cloud landing) is queued for next dispatch.

## Context
Plan 005 ships gateway-only cloud Hermes. MCP tool calls are absent for the duration of the soak — by design (Plan 008 lands them). Phase H is the paper trail.

## Dependencies
- Phase 005-G complete + green

## Scope

### Files to Create
None.

### Files to Modify
- `plans/PROGRESS.md` — mark 005 COMPLETE
- `plans/005-fargate-cutover-stage1/STATUS.md` — final summary block with image digest, cost during soak, interaction count, restart count, P95 latency
- `plans/cross-repo-tier-graph.md` (in agentic-hub) — add Plan 005 COMPLETE + Plan 008 NOT STARTED rows

### Explicitly Out of Scope
- Writing Plan 006 (already exists)
- Writing Plan 008 (already exists)
- Archiving Plan 005 — keep active until Plan 008 closes the MCP loop

## Implementation Notes

1. **Final summary block** should be operational, not narrative. Use a table format with hard numbers: image digest, total Fargate cost during soak, message count, restart count, P95 latency.
2. **Plan 008 dispatch** is a separate user decision — Phase H just makes sure it's discoverable in PROGRESS + tier-graph.
3. **Archive timing**: archive Plan 005 AFTER Plan 008 ships, not now. Plan 005 + 008 are sibling cutover phases; archiving 005 alone is premature.

## Acceptance Criteria
- [ ] `plans/PROGRESS.md` row for 005 updated to `COMPLETE 2026-MM-DD` with metrics summary
- [ ] `plans/005-fargate-cutover-stage1/STATUS.md` has Final Summary block with: v8 image digest, total soak cost (USD), interaction count, P95 reply latency, restart count
- [ ] `plans/cross-repo-tier-graph.md` (in agentic-hub) updated with Plan 005 COMPLETE + Plan 008 ready-to-dispatch
- [ ] Commit message ties Plan 005 closure to Plan 008 ready-state
- [ ] Branch pushed; PR opened or merged (depending on workflow)

## Verification Steps

```bash
# Read final state of trackers
cat plans/PROGRESS.md | head -15
cat plans/005-fargate-cutover-stage1/STATUS.md | tail -25
cat /Users/blakeaber/Documents/agentic-hub/plans/cross-repo-tier-graph.md 2>/dev/null | grep -E "005|008" || echo "tier-graph not present in agentic-hub yet"
```

## Status
Not started
