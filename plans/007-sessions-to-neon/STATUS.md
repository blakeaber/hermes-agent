# Status — Plan 007: Sessions to Neon

**Status:** NOT STARTED
**Last updated:** 2026-05-25
**Blocked by:** None — first phase is migration-only and unblocked immediately
**Blocks:** Plan 005 (Fargate cutover) cannot ship cleanly until 007 lands — cloud Fargate has no persistent disk

## Phase Progress

| Phase | Title | Status | Notes |
|---|---|---|---|
| 007-A | Migration + schema (raw_events + RLS) | **Complete (2026-05-25)** | Migration applied to live Neon; raw_events with RLS + grants verified; 4 acceptance tests pass (insert, isolation, dual-tenant, idempotency) |
| 007-B | NeonBackend session-entry CRUD + raw_events write | **In progress** | Reduced scope: only `append_raw_event` is new (other CRUD already exists in Plan 001-D) |
| 007-C | SessionStore backend selection + JSONL drop in saas mode | Not started | Depends on 007-B |
| 007-D | Raw audit hooks (inbound + outbound + tool call) | Not started | Depends on 007-C |
| 007-E | End-to-end UAT (Slack → Neon round-trip + restart survival) | Not started | Depends on 007-D |

## Resumption context

- Next phase: 007-B (in progress)
- Adaptations recorded below — Phase B + C scope reduced after schema inspection.

## Open Questions (none blocking)

- Whether `SQLiteBackend` should stub the new methods or raise `NotImplementedError` — left to implementer's judgment in Phase 007-B per Implementation Note #5
- Whether to remove `SessionDB` (`hermes_state.py`) after Plan 007 settles — deferred; keep for rollback safety

## Adaptations log
_(records any mid-execution deviations from the phase files)_

### 2026-05-25 — Phase 007-A scope reduction after schema inspection

When Phase 007-A inspected the live Neon DB, found that Plan 001-D already shipped MORE than the master plan credited:

- The table called `sessions` in Plan 007's master plan is actually `conversations` (Plan 001-D semantics). Same concept; just renamed in spec to align.
- `messages` table already exists with `(id, conversation_id, tenant_id, user_id, role, content, tool_calls, metadata, created_at)` + RLS policy. The SQLite-extras (`tool_name`, `tool_call_id`, `reasoning`, `reasoning_content`, `reasoning_details`, `codex_reasoning_items`, `codex_message_items`) do NOT exist as columns — but will be stuffed into the `metadata` JSONB on write. **No ALTER TABLE needed.**
- `NeonBackend` already has: `get_or_create_conversation`, `append_message`, `get_conversation_history`, `search_sessions`, `_get_or_create_user`. **Phase 007-B's "5 new methods" shrinks to 1: `append_raw_event`.**

**Net effect:**
- Phase 007-A → only the new `006_raw_events.sql` migration (no other DDL needed)
- Phase 007-B → only the `append_raw_event` method + 1 test (was: 5 new methods + 5 tests)
- Phase 007-C → unchanged but now uses existing `get_or_create_conversation` + `append_message` rather than new methods
- Phase 007-D → unchanged
- Phase 007-E → unchanged (UAT verifies the wiring, not new code)

Estimated effort revised down from ~2 days to ~1 day total.
