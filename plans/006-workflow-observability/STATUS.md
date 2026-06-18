# Status — Plan 006: Workflow Observability

**Status:** DRAFT
**Last updated:** 2026-05-25
**Blocked by:** None (006-A unblocked immediately)
**Blocks:** None

## Phase Progress

| Phase | Title | Status | Notes |
|-------|-------|--------|-------|
| 006-A | Workflow Event Log (SQLite) | Not started | Unblocked — start here |
| 006-B | Rooben Verifier Surface | Not started | Depends on 006-A |
| 006-C | Linear Issue Enrichment | Not started | Depends on 006-A; parallel with 006-B |
| 006-D | Slack /workflow Commands | Not started | Depends on 006-A + 006-B |

## Open Questions (resolve before Phase 006-B begins)

- **Q-6.1**: Does `_dispatch_to_rooben()` already return the verifier output, or does it only return the final answer? Check `run_agent.py` for the return value of that function.
- **Q-6.2**: Is `rooben-planning/` the same verifier as the one referenced in `agentic-hub/rooben-planning/`? Confirm path via `find ~/Documents -name "verifier.py" 2>/dev/null`.

## Open Questions (resolve before Phase 006-C begins)

- **Q-6.3**: Is Linear accessed via `tools/linear_tools.py` directly, or via an MCP server entry in `~/.hermes/config.yaml`? Run: `python3 -c "import yaml; c=yaml.safe_load(open('/Users/blakeaber/.hermes/config.yaml')); print(list(c.get('mcp_servers',{}).keys()))"` to check.

## Resumption Context

- Next phase: 006-A
- Source feedback: Slack #product-feedback ts 1779051268, 1779051395, 1779051463 (all from U0B1DFUS1D2, week of 2026-05-18)
- Pre-kickoff: read `run_agent.py` → search for `_dispatch_to_rooben` and `run_conversation` to understand the hook points before writing phase files
- No adaptations yet.
