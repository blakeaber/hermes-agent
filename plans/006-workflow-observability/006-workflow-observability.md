# Plan 006: Workflow Observability — Task DAG Transparency, Rooben Verifier Surface & Linear Enrichment

**Status:** DRAFT
**Date:** 2026-05-25
**Branch:** feat/006-workflow-observability (to be created)
**Depends on:** None (006-A is fully unblocked; 006-B needs 006-A complete)

---

## Context

Three messages posted to `#product-feedback` (Slack ts: 1779051268, 1779051395, 1779051463) articulate the same core pain: Hermes drives tasks and creates Linear issues, but there is no visibility into the work breakdown — users can't see the workflow structure, Rooben's verification output, or the metadata that explains why issues were created. Compounding this, the relationship between Hermes and Rooben Pro is invisible: users don't know when Hermes is doing the work vs. delegating to Rooben.

These three feedback items cluster around a single capability gap: **workflow observability**. A durable event log with a Slack surface closes it.

The `005-fargate-cutover-stage1` plan (infrastructure) creates the cloud runtime that this plan's observability layer will run in — but 006 does not depend on 005 landing first. The SQLite event log (Phase 006-A) works locally today.

## Key Design Insights

1. **SQLite first, Neon later** — The event log starts as a local SQLite DB at `~/.hermes/observability/events.db`. It migrates to Neon only when Hermes runs in Fargate (HERMES_MODE=saas). This keeps Phase 006-A self-contained.
2. **Rooben integration point already exists** — `_dispatch_to_rooben()` in `run_agent.py` is the single hook. Phase 006-B wraps it, not the entire Rooben stack.
3. **Linear enrichment is config-layer** — Hermes already creates Linear issues via `tools/linear_tools.py` or the MCP server. Phase 006-C adds metadata injection at the call site. No new Linear API permissions needed.

---

## Phase Index

| Phase | Title | Effort (1-5) | Risk (1-5) | Priority | Dependencies | Status |
|-------|-------|-------------|-----------|----------|--------------|--------|
| 006-A | Workflow Event Log (SQLite) | 2 | 1 | P0 | None | Not started |
| 006-B | Rooben Verifier Surface | 3 | 2 | P0 | 006-A | Not started |
| 006-C | Linear Issue Enrichment | 2 | 1 | P0 | 006-A | Not started |
| 006-D | Slack `/workflow` Commands | 2 | 2 | P1 | 006-A, 006-B | Not started |

## Execution Sequence

```
006-A → 006-B → 006-D
006-A → 006-C
```

(006-B and 006-C can run in parallel after 006-A is complete.)

---

## Phase Details

### Phase 006-A — Workflow Event Log (SQLite)

**What:** Add a lightweight SQLite event log at `~/.hermes/observability/events.db`. Every agent turn records: turn_start, tool calls, rooben_dispatch, rooben_verification, linear_issue_created, turn_complete. A `workflow_id` ties events from a single user prompt together. This is the foundation all other phases build on.

**Originating feedback:**
- Slack ts=1779051463: "I wish I had more structured access to workflows, specifications, task DAGs, outputs and quality verification for all Hermes input prompts. It is very challenging to inspect the inputs / outputs of requested work."
- Slack ts=1779051395: "I wish I could understand how Rooben Pro was deconstructing complex work into tasks — currently, I don't know when Hermes is doing it vs. Rooben."

**Files to modify:**
- `tools/workflow_events.py` — CREATE: EventLogger class with log_event(), get_or_create_workflow_id(), query_events()
- `run_agent.py` — extend run_conversation() to call EventLogger at turn start/end
- `~/.hermes/observability/` — CREATE: directory + schema migration on first use

**Acceptance criteria:**
- [ ] `~/.hermes/observability/events.db` is created on first agent run
- [ ] Each turn produces at minimum two rows: `turn_start` and `turn_complete`
- [ ] `EventLogger().query_events(workflow_id=X)` returns ordered list of events for that workflow
- [ ] `pytest tests/test_workflow_events.py -v` — all pass

### Phase 006-B — Rooben Verifier Surface

**What:** Wrap `_dispatch_to_rooben()` to capture the Rooben LLM Verifier output (PASS/FAIL + criteria breakdown) and store it as a `rooben_verification` event in the log. Also expose a re-verification endpoint so `/workflow verify <id>` in Phase 006-D can replay verification without re-execution.

**Originating feedback:**
- Slack ts=1779051395: "I want to leverage Rooben's LLM Verifier output."

**Files to modify:**
- `run_agent.py` — wrap `_dispatch_to_rooben()` call site; capture verifier result
- `tools/workflow_events.py` — add `log_rooben_verification(workflow_id, spec, result)` helper
- `tests/test_rooben_verifier_surface.py` — CREATE: unit tests with mocked rooben response

**Acceptance criteria:**
- [ ] After any turn that triggers Rooben, `rooben_verification` event exists in the log with `passed`, `criteria` fields
- [ ] Re-verification callable without re-executing the task (spec-only mode)
- [ ] `pytest tests/test_rooben_verifier_surface.py -v` — all pass

### Phase 006-C — Linear Issue Enrichment

**What:** Inject provenance metadata into Linear issues created by Hermes: workflow ID, plan reference, dependency list, and a `hermes-generated` label. The description block prepends a Hermes provenance header. No new Linear API permissions required.

**Originating feedback:**
- Slack ts=1779051268: "I wish there was more context, visibility into dependencies, description of 'projects' that issues apply to, and other metadata associated with the Hermes workflows that generate issues in Linear."

**Files to modify:**
- `tools/linear_tools.py` (or MCP wrapper in `model_tools.py` if Linear is MCP-only — check `~/.hermes/config.yaml` mcp_servers) — inject provenance block at issue creation
- `tools/workflow_events.py` — add `log_linear_issue_created(workflow_id, issue_id, issue_url)` helper

**Acceptance criteria:**
- [ ] Linear issue description starts with `🤖 Created by Hermes / Workflow: wf-{id} / Plan: {ref or ad-hoc} / Dependencies: {list or none}`
- [ ] `hermes-generated` label applied on creation (label must be pre-created manually in Linear once)
- [ ] `log_linear_issue_created` event appears in the event log with the issue URL
- [ ] Falls back gracefully if workflow context unavailable (uses `ad-hoc` rather than crashing)

### Phase 006-D — Slack `/workflow` Commands

**What:** Add three Slack slash commands — `/workflow list`, `/workflow show <id>`, `/workflow verify <id>` — that surface the event log and trigger Rooben re-verification from Slack. Alias `/wf` for convenience.

**Originating feedback:**
- Slack ts=1779051463: "It is very challenging to inspect the inputs / outputs of requested work."
- Slack ts=1779051395: "I want to leverage Rooben's LLM Verifier output."

**Files to modify:**
- `hermes_cli/commands.py` — register `workflow` CommandDef with subcommands list/show/verify, alias `wf`
- `tools/workflow_events.py` — add `format_workflow_summary()` and `format_workflow_detail()` formatters
- `gateway/platforms/slack.py` — route `/workflow` slash commands to the command handler

**Acceptance criteria:**
- [ ] `/workflow list` returns last ≤10 workflows with IDs, timestamps, event counts, statuses
- [ ] `/workflow show wf-{id}` returns human-readable step-by-step event log
- [ ] `/workflow verify wf-{id}` triggers Rooben re-verification and posts PASS/FAIL breakdown
- [ ] `/wf list` alias works identically
- [ ] Unknown workflow ID returns friendly error, not a crash

---

## Budget Estimate

| Component | Cost |
|-----------|------|
| SQLite at `~/.hermes/observability/` | $0 (local) |
| Neon (when HERMES_MODE=saas) | $0 (within existing Neon free tier) |
| Linear API calls (enrichment metadata) | $0 (standard issue creation) |
| Total new infra cost | **$0/mo** |
