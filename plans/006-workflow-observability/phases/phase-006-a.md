# Phase 006-A: Workflow Event Log (SQLite)

## Goal
Create a durable SQLite event log at `~/.hermes/observability/events.db` that records each agent turn's workflow ID, tool calls, and final output — giving Blake a queryable history of everything Hermes did.

## Context
Three `#product-feedback` messages (ts: 1779051463, 1779051395, 1779051268) converge on one gap: there is no way to inspect what Hermes actually did during a turn. Without an event log, Phases 006-B, 006-C, and 006-D have no foundation.

This phase is fully unblocked. It does not depend on any other plan.

## Dependencies
None.

## Scope

### Files to Create
- `tools/workflow_events.py` — EventLogger class: schema creation, `log_event()`, `get_or_create_workflow_id()`, `query_events()`, `format_workflow_summary()`, `format_workflow_detail()`
- `~/.hermes/observability/` — directory created by EventLogger on first instantiation
- `tests/test_workflow_events.py` — unit tests (mocked DB path)

### Files to Modify
- `run_agent.py` — call `EventLogger().log_event('turn_start', ...)` at the top of `run_conversation()` and `EventLogger().log_event('turn_complete', ...)` before the final return

### Explicitly Out of Scope
- Neon persistence (HERMES_MODE=saas) — deferred to a future phase when 006 is validated locally
- Tool-level event granularity (individual tool call events) — not needed for Phase 006-A; can be added in 006-B

## Implementation Notes

**Schema (SQLite):**
```sql
CREATE TABLE IF NOT EXISTS workflow_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    event_type  TEXT NOT NULL,   -- 'turn_start', 'turn_complete', 'rooben_dispatch', etc.
    ts          REAL NOT NULL,   -- Unix epoch float (matches Slack ts format)
    session_id  TEXT,
    metadata    TEXT             -- JSON blob, optional
);
CREATE INDEX IF NOT EXISTS idx_workflow_id ON workflow_events(workflow_id);
CREATE INDEX IF NOT EXISTS idx_ts ON workflow_events(ts DESC);
```

**Workflow ID generation:** `wf-` + first 6 chars of `uuid.uuid4().hex`. Generate once per `run_conversation()` call, store in a local variable, pass to all log_event calls in that turn.

**EventLogger constructor:** accept optional `db_path` kwarg (defaults to `get_hermes_home() / 'observability' / 'events.db'`). Creates the directory and runs `CREATE TABLE IF NOT EXISTS` on first call. Thread-safe via `threading.local()` connection.

**query_events() signature:**
```python
def query_events(self, workflow_id: str = None, limit: int = 50, since_ts: float = None) -> list[dict]:
```

**format_workflow_summary():** Returns one-line string: `wf-{id} · {datetime} · {N} events · {status}`

**format_workflow_detail():** Returns multi-line string with each event as a numbered step (see Phase 006-D Implementation Notes for format).

## Acceptance Criteria
- [ ] `~/.hermes/observability/events.db` is created on first agent run (SQLite file exists, schema applied)
- [ ] Each agent turn produces ≥2 rows: one `turn_start` event and one `turn_complete` event, both sharing the same `workflow_id`
- [ ] `EventLogger().query_events(workflow_id='wf-abc123')` returns events in ascending `ts` order
- [ ] `EventLogger().query_events(limit=10)` returns the 10 most recent events regardless of workflow
- [ ] `pytest tests/test_workflow_events.py -v` — all pass (use `tmp_path` fixture for isolated DB)
  - Source: Slack ts=1779051463, ts=1779051395 (#product-feedback)

## Verification Steps
```bash
# 1. Run tests
cd ~/Documents/hermes-agent
pytest tests/test_workflow_events.py -v
# Expected: all pass

# 2. Start a Hermes session (or run a quick cron)
hermes chat -z "What is 2+2?" 2>/dev/null

# 3. Confirm events were written
sqlite3 ~/.hermes/observability/events.db \
  "SELECT workflow_id, event_type, ts FROM workflow_events ORDER BY ts DESC LIMIT 5;"
# Expected: 2 rows (turn_start + turn_complete) sharing a workflow_id

# 4. Confirm query_events
python3 -c "
from tools.workflow_events import EventLogger
el = EventLogger()
events = el.query_events(limit=5)
print(events)
"
# Expected: list of dicts with workflow_id, event_type, ts, metadata
```

## Status
Not started

## Bug Log
| # | Description | Status |
|---|-------------|--------|
