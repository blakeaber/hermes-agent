-- =====================================================================
-- Migration 008: clarify_pending — orchestrator clarification relay state
-- =====================================================================
-- Plan 074-C (clarification relay, Hermes side).
--
-- Correlates a Slack thread with an in-flight orchestrator workflow that
-- asked a clarifying question. The orchestrator POSTs a question to the
-- Hermes ingress (gateway/clarify_relay.py), which posts it into the
-- Slack thread AND writes one row here keyed by the thread anchor. When
-- the user replies in that thread, the gateway's Slack message handler
-- looks the thread up here and POSTs the answer back to the orchestrator
-- sensor's /clarify/reply route, then deletes the row.
--
-- Why a table (not in-memory):
--   The inbound ingress runs in the health-server process (:8080) while
--   the Slack Socket-Mode reply is observed by the separate gateway
--   process. The two share no memory, so the thread→workflow mapping
--   MUST be durable + cross-process. Neon is the shared substrate both
--   processes already connect to via hermes_storage.get_backend().
--
-- No RLS:
--   Unlike tenants/messages/raw_events, this is ops-correlation state,
--   not tenant content. It is keyed by the globally-unique Slack thread
--   anchor (channel:thread_ts) and is read/written by both the ingress
--   and the gateway without an app.tenant_id transaction context. We
--   therefore deliberately do NOT enable row-level security here and
--   grant the hermes_app role full CRUD (including DELETE, which the
--   reply path needs to consume a pending row).
--
-- Idempotency:
--   thread_ref is the PRIMARY KEY. A re-POST of the same question for the
--   same thread (orchestrator retry) upserts (ON CONFLICT DO UPDATE),
--   refreshing the question + workflow_id rather than duplicating.
-- =====================================================================

-- 1) Table -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS clarify_pending (
    thread_ref   text PRIMARY KEY,            -- Slack anchor "channel:thread_ts"
    workflow_id  text NOT NULL,               -- orchestrator workflow id to answer
    question     text NOT NULL DEFAULT '',    -- the question asked (echoed back)
    identifier   text,                        -- opaque orchestrator identifier (issue/phase ref)
    created_at   timestamp with time zone NOT NULL DEFAULT now()
);

-- 2) Indexes ---------------------------------------------------------
-- Reap stale pending rows by age (a future sweeper / TTL job).
CREATE INDEX IF NOT EXISTS clarify_pending_created_idx
    ON clarify_pending (created_at);

-- 3) Grants ----------------------------------------------------------
-- Full CRUD: the reply path DELETEs the row once consumed.
GRANT SELECT, INSERT, UPDATE, DELETE ON clarify_pending TO hermes_app;

-- 4) Comments --------------------------------------------------------
COMMENT ON TABLE clarify_pending IS
    'Plan 074-C: orchestrator clarification relay state. Maps a Slack thread '
    '(channel:thread_ts) to the workflow that asked a question. Written by the '
    'health-server ingress, consumed (and deleted) by the gateway Slack reply '
    'handler. No RLS — ops-correlation state keyed by a global thread anchor.';

COMMENT ON COLUMN clarify_pending.thread_ref IS
    'Slack thread anchor "channel_id:thread_ts". Primary key / idempotency key.';

COMMENT ON COLUMN clarify_pending.workflow_id IS
    'Orchestrator workflow id; POSTed back in the /clarify/reply body.';
