# Status — Plan 008: MCPGateway Production Wiring

**Status:** SCOPED-DOWN + DEFERRED (2026-05-31)
**Last updated:** 2026-05-31
**Blocked by:** Trigger condition — "Hermes-style MCP-backed agents are added to the orchestrator swarm" (or equivalent R6/R3 trigger; see Adaptations log).

## 2026-05-31 scope-down (Plan 027-C)

Per [D2 Recommendation R6 caveat](../../../../agentic-hub/docs/research/dimensions/D2-critique-recommendations.md) and the
[R3 30-agent-scale adversarial review](../../../../agentic-hub/docs/research/reviews/R3-30-agent-scale-adversarial.md),
Plan 008 is scoped down — not killed — and the residual work is now tracked as
Linear issue `PV-124` (`follow-up:008`).

R3's deferral logic (quoted verbatim):

> "MCPGateway sidecar + real auth-gating is conditional on Hermes-style
> agents entering the orchestrator swarm. At solo-operator MVP scale
> (5 agents over 12h, single user, no multi-tenant traffic) the
> per-session local MCP fan-out cost and the open-access default are
> acceptable trade-offs against shipping the swarm at all. Re-open
> Plan 008 the moment that trigger fires; until then, keep the row
> on the follow-up sweep instead of carrying it on a live plan list."

This rationale aligns with the
[scheduling contract](../../../../agentic-hub/docs/architecture/scheduling-contract.md)
shipped in Plan 027-A: the contract's matrix lists
"Kanban worker spawn" as **REMOVED** (replaced by a future shared-backlog
drain when an R1 trigger fires), and MCPGateway does not appear in the
matrix as a primitive in its own right — by design.

## Phase Progress

| Phase | Title | Status | Notes |
|---|---|---|---|
| 008-A | Audit MCPGateway: does it actually run? | DEFERRED | Confirmed by integration report O4 (2026-05-31): `_server_requires_auth` is a `return False` stub; `gateway/run.py` has no MCPGateway import. No code work needed on 008-A — the audit's answer is "not adopted." Resume work as part of PV-124. |
| 008-B | Wire MCPGateway into `gateway/run.py` startup | DEFERRED | Folded into PV-124. |
| 008-C | Local load test: 10 concurrent tool calls → no per-call subprocess | DEFERRED | Folded into PV-124. |
| 008-D | Migrate 5 MCP credentials to Secrets Manager | DEFERRED | Folded into PV-124. |
| 008-E | Deploy MCPGateway sidecar to Fargate task def | DEFERRED | Folded into PV-124. |
| 008-F | Cloud smoke test: Slack mention → tool call → response, P95 ≤ 1.5× local | DEFERRED | Folded into PV-124. |
| 008-Kanban (implicit) | Kanban dispatcher re-enable via pooled MCPGateway | **REMOVED** | Replaced by the future shared-backlog drain when an R1 trigger fires. See [scheduling contract](../../../../agentic-hub/docs/architecture/scheduling-contract.md) matrix row "Kanban worker spawn → REMOVED." Per [feedback memo on kanban dispatcher](~/.claude/projects/-Users-blakeaber-Documents-agentic-hub/memory/feedback_kanban_dispatcher.md), `kanban.dispatch_in_gateway=false` stays pinned until the backlog drain ships. |

## Trigger condition (when to resume Plan 008)

Re-open this plan when **any** of the following fires (these are the same triggers cited on Linear PV-124):

1. Hermes-style MCP-backed agents join the orchestrator swarm — e.g., new agent classes under `orchestrator/agents/` that depend on MCP tool calls.
2. The 2026-05-21 OOM symptom recurs (per-worker MCP subprocess fan-out exhausts laptop RAM) under the post-Plan 029 drain.
3. A security review escalates the `_server_requires_auth = return False` stub from P1 to P0 (e.g., multi-tenant traffic added).

Until then, this plan is parked. The Linear row keeps the debt visible to Plan 028's weekly follow-up sweep.

## Residual debt (tracked on Linear PV-124)

- Real `_server_requires_auth` policy reading `auth_required` flag from server descriptor; deny-by-default for new servers.
- Wire `MCPGateway` into `gateway/run.py` startup (Plan 002-C's class is shipped + 16 tests pass, but never adopted at runtime).
- Cloud MCP credential migration to Secrets Manager.
- MCPGateway → Fargate sidecar deploy.
- Load test + cloud smoke test (P95 ≤ 1.5× local).

## Adaptations log

- **2026-05-31 (Plan 027-C):** Scoped down per D2 R6 caveat + R3 deferral logic. Kanban path REMOVED (replaced by future shared-backlog drain when R1 trigger fires); MCPGateway wiring + real auth-gating DEFERRED behind the swarm-Hermes-agents trigger. Linear issue PV-124 (`follow-up:008`) opened to capture the residual security gap (`_server_requires_auth` stub from integration report O4) and the sidecar deploy. Cross-references the scheduling contract published in Plan 027-A. Phase rows above flipped from "Not started" to "DEFERRED" or "REMOVED" accordingly.

## References

- Plan 008 master spec: `plans/008-mcpgateway-production-wiring/008-mcpgateway-production-wiring.md`
- Linear follow-up row: `PV-124 — Plan 008 follow-up: real MCP auth-gating + sidecar deployment` (label `follow-up:008`)
- Scope-down rationale: `/Users/blakeaber/Documents/agentic-hub/plans/027-scheduling-contract/027-scheduling-contract.md` §"Phase 027-C"
- Scheduling contract: `/Users/blakeaber/Documents/agentic-hub/docs/architecture/scheduling-contract.md`
- D2 R6 (problem + proposed change): `/Users/blakeaber/Documents/agentic-hub/docs/research/dimensions/D2-critique-recommendations.md` §"Recommendation 6"
- R3 deferral logic: `/Users/blakeaber/Documents/agentic-hub/docs/research/reviews/R3-30-agent-scale-adversarial.md`
- Integration report O4 (`_server_requires_auth` stub): `/Users/blakeaber/Documents/agentic-hub/docs/research/dimensions/D2-critique-recommendations.md` §O4
- Original 2026-05-21 OOM memo: `~/.claude/projects/-Users-blakeaber-Documents-agentic-hub/memory/feedback_kanban_dispatcher.md`
