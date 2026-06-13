# Plans — Hermes Agent Global Progress

| Plan | Title | Status | Run after |
|------|-------|--------|-----------|
| 001 | Multi-User SaaS Hermes — Identity, Scoped Skills & Memory, Cloud Storage | **IN PROGRESS** (Phases 0/A/B/C/D Complete 2026-05-20; Phase E code complete — AWS apply pending). 6 phases (0, A, B, C, D, E). All code shipped; D + E need `terraform apply`. | — |
| 002 | Hermes Self-Organization — Directory Structure, MCP Pool, Runtime Isolation | DRAFT (2026-05-18) — 4 phases (A, B, C, D). Defines the canonical directory layout, pooled MCP gateway, runtime workspace isolation, credential injection. Cloud-routable via env vars. | 001-0 |
| 003 | Skills Service — Scoped Registry, MCP Surface, Git-Backed Collaboration | **COMPLETE** (2026-05-20) — All 6 phases (A–F) shipped. Standalone repo (`hermes-skills-service/`), port 8001, CSS scope resolution, Git-backed registries, promotion CLI, advisory write locks, S3 backend (HERMES_MODE=saas). hermes-saas-skills bucket live; round-trip verified. Supersedes Plan 001-A. | 001-0 |
| 004 | Self-Improvement Service — Hermes↔Skills↔Atlas Feedback Loop | STUB (2026-05-18) — Stub plan only. No phases yet. Defines the boundary between Hermes agent behavior scoring, Skills Service promotion, and Atlas memory. Port 8002 (TBD). | 003 + Atlas 012 |
| 005 | Hermes Fargate Cutover Stage 1 (gateway only) | DRAFT (2026-05-23) — 8 phases (A–H). Moves Hermes gateway to Fargate; MCPs stay local. **Blocked by Plan 007.** | 001-E + Plan 007 |
| 006 | Workflow Observability — Task DAG, Rooben Verifier Surface, Linear Enrichment | DRAFT (2026-05-25) — Slack-surfaced workflow event log. SQLite locally, Neon in saas mode. | None |
| 007 | Sessions to Neon — Compliance-Grade Audit + Cloud-Survivable State | **COMPLETE 2026-05-25** — All 5 phases shipped. Slack adapter persists user + assistant turns + raw audit + reactions to Neon. Live UAT: 19 messages + 19 outbound audit + 1 inbound audit + 1 reaction. Restart-survival proven. 7 commits on feat/plan-004-self-improvement. Surfaced + fixed 3 pre-existing bugs (SlackResponse.data, Slack scope, get_conversation_history cold-start). | 001-D |
| 008 | MCPGateway Production Wiring — Pooled MCPs in Cloud Without Per-Worker Fan-Out | DRAFT (2026-05-25) — 6 phases (A–F). Audits + activates Plan 002-C's MCPGateway in gateway startup; deploys as Fargate sidecar so cloud Hermes can call MCP tools without per-session subprocess explosion. | Plan 005 soak passes |

## Active plans

- **001 — Multi-User SaaS** (IN PROGRESS 2026-05-20): All 6 phases code-complete. Phase E shipped 2026-05-20: `Dockerfile.saas` (Python 3.12-slim, multi-stage, stateless), `gateway/health.py` (Neon+S3 concurrent checks), `gateway/health_server.py` (aiohttp :8080), 10 tests pass, `docker-compose.saas.yml`, Terraform module `infra/terraform/hermes-fargate/` (5 to add), `scripts/build-push-saas.sh`. ECR image pushed: `agentic-stack/hermes:plan-001-E` (sha256:23a9a91). Two `terraform apply` gates remain: Phase D (`infra/terraform/s3-skills-bucket/`) and Phase E (`infra/terraform/hermes-fargate/`).
- **002 — Hermes Self-Organization** (2026-05-18): Spec complete at `~/.hermes/STRUCTURE.md` (v2.0). Plan lives at `plans/002-hermes-self-organization/`. Not started — awaiting Plan 001-0 (HermesIdentity dataclass).
- **003 — Skills Service** (COMPLETE 2026-05-20): All 6 phases shipped. S3RegistrySkillSource in hermes-skills-service/sources/s3_source.py; Resolver delegates to S3 when HERMES_MODE=saas; 37 tests pass (28 unit + 9 original service + 1 live against hermes-saas-skills).
- **004 — Self-Improvement Service** (STUB 2026-05-18): Placeholder only. Real spec TBD after Skills Service (003) + Atlas 012 (Hermes↔Atlas connector) complete.

## Cross-repo consistency pass

Completed + corrected 2026-05-18. See `plans/CONSISTENCY-PASS.md` for full inventory and findings across all four repos (hermes-agent, army-of-one, rooben-pro, agentic-hub). Key findings:
- agentic-hub Plans 001–008 are ALL COMPLETE. Stack is healthy (1 container: atlas only).
- agentic-hub/rooben-planning/ IS the Rooben planning core, vendored in-process (Plan 005-F). The `/refine` + Specification + LLMPlanner pipeline IS available to Hermes via `_dispatch_to_rooben()`.
- Atlas Plan 014 is IN PROGRESS (A–F done; G–I remain). Does not block Hermes execution.
- Hermes 001-0 (HermesIdentity) is the single critical-path gating item for all Hermes SaaS plans.
- Port assignments confirmed: Atlas=8000, Skills=8001, Self-Improvement=8002 (TBD).
- Format fixes applied: Plan 001 renamed to `001-saas-multi-user/phases/`; Atlas 010/011/012 `phases/` dirs created.

## Completed plans (archived)

_(none yet)_

---

## Inline sub-tasks (feedback triage — nightly, no new plan)

### [BUG] Slack home channel not resolved at agent send time
- **Source:** #product-feedback Slack message (ts: 1780166688.543969, user: U0B1DFUS1D2)
- **Triage:** `bug`
- **Symptom:** Hermes agent reports "no home channel has been set" at send time even though `SLACK_HOME_CHANNEL=D0B246RSJC8` is present in `~/.hermes/.env`. The gateway itself reads the env correctly (gateway.log shows it connected and uses D0B246RSJC8). The failure path appears to be in the agent-side `send_message` tool, which may load config independently of the gateway env vars.
- **Suggested fix:** Verify that `~/.hermes/.env` is loaded before the `send_message` / Slack tool code path resolves `SLACK_HOME_CHANNEL`. Check `tools/` for any Slack send tool that independently reads env vs the gateway config.
- **Effort:** S (< 1 day)
- **Routing:** Fix in `tools/` or `gateway/platforms/slack.py` send path; no new phase needed.
- **Added:** 2026-06-03 (nightly triage)

### [UX] Hermes incorrectly refuses Atlas memory / cross-session recall with a privacy non-answer
- **Source:** #product-feedback Slack message (ts: 1780166624.427729, user: U0B1DFUS1D2)
- **Triage:** `ux`
- **Symptom:** When asked about memories from other sessions or to reference Atlas, Hermes responds: "I'm sorry, but I can't share specific details about our past conversations due to privacy and security reasons." This is a hallucinated refusal — the memory tool and Atlas connector (atlas-012) exist and are intended to be used. The agent is either not receiving the Atlas context in its system prompt, or a safety heuristic in the system prompt is over-triggering.
- **Suggested fix:** (a) Verify `memory_tool.py` and Atlas connector are registered in the agent's toolset and not accidentally gated. (b) Audit the system prompt / persona for overly cautious privacy language that could confuse the model. (c) Add an acceptance-test prompt: "What do you know about me from Atlas?" → should return actual memory content, not a refusal.
- **Effort:** S–M (half day investigation + fix + test)
- **Routing:** Could touch `tools/memory_tool.py`, `agent/` system prompt templates, or `hermes_constants.py` memory path resolution. No new phase needed — but if Atlas connector is simply not wired, may surface as a blocker for Plan 004 post-ship validation.
- **Added:** 2026-06-03 (nightly triage)
