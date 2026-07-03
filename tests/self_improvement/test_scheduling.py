"""
tests/self_improvement/test_scheduling.py

Unit tests for hermes_agent.self_improvement.scheduling — the ticker activation
seam that fires the Plan 004 jobs (scoring/promotion/drift/recommender) and the
weekday morning brief on an internal last-run gate.

All tests are hermetic: the state file is redirected to tmp, the Neon pool and
Slack client are mocked, and time is injected. No live gateway / Neon / Slack.

Inventory:
  1. _is_due — never-run / recent / stale
  2. maybe_run_self_improvement no-ops without a saas pool (local mode)
  3. maybe_run_self_improvement dispatches + advances state when due
  4. maybe_run_self_improvement is idempotent (second immediate call not due)
  5. run_daily_cycle fans out to scorer + promotion + drift
  6. run_weekly_cycle fans out to recommender per tenant
  7. daily brief: weekend skip / before-time skip / no-channel skip
  8. daily brief: fires once per local day, guarded on the second call
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hermes_agent.self_improvement import scheduling


@pytest.fixture(autouse=True)
def _tmp_state(tmp_path, monkeypatch):
    """Redirect the scheduler state file into a temp dir."""
    state = tmp_path / ".scheduler_state"
    monkeypatch.setattr(scheduling, "_state_file", lambda: state)
    return state


# ---------------------------------------------------------------------------
# 1. _is_due
# ---------------------------------------------------------------------------

def test_is_due_never_run():
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    assert scheduling._is_due(None, now, 20) is True


def test_is_due_recent_not_due():
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    last = (now - timedelta(hours=2)).isoformat()
    assert scheduling._is_due(last, now, 20) is False


def test_is_due_stale():
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    last = (now - timedelta(hours=25)).isoformat()
    assert scheduling._is_due(last, now, 20) is True


# ---------------------------------------------------------------------------
# 2-4. maybe_run_self_improvement
# ---------------------------------------------------------------------------

def test_self_improvement_noop_without_pool():
    """Local / non-saas mode: no pool → no scheduling, no state written."""
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    with patch.object(scheduling, "_get_pool", return_value=None):
        result = scheduling.maybe_run_self_improvement(loop=MagicMock(), now=now)
    assert result is None


def _closing_scheduler(sentinel):
    """Mock safe_schedule_threadsafe that closes the coroutine it's handed
    (the real loop would consume it) and returns a sentinel future."""

    def _side_effect(coro, loop, **kwargs):
        coro.close()
        return sentinel

    return _side_effect


def test_self_improvement_dispatches_and_advances_state(_tmp_state):
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    sentinel = MagicMock(name="future")
    with patch.object(scheduling, "_get_pool", return_value=MagicMock()), patch(
        "agent.async_utils.safe_schedule_threadsafe",
        side_effect=_closing_scheduler(sentinel),
    ) as sched:
        result = scheduling.maybe_run_self_improvement(loop=MagicMock(), now=now)

    assert result is sentinel
    sched.assert_called_once()
    # State advanced for both daily + weekly (first run → both due).
    state = scheduling._load_state()
    assert state["daily_last_run_at"] is not None
    assert state["weekly_last_run_at"] is not None


def test_self_improvement_idempotent_second_call(_tmp_state):
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    sentinel = MagicMock(name="future")
    with patch.object(scheduling, "_get_pool", return_value=MagicMock()), patch(
        "agent.async_utils.safe_schedule_threadsafe",
        side_effect=_closing_scheduler(sentinel),
    ) as sched:
        first = scheduling.maybe_run_self_improvement(loop=MagicMock(), now=now)
        # Same instant: nothing is due anymore.
        second = scheduling.maybe_run_self_improvement(
            loop=MagicMock(), now=now + timedelta(minutes=5)
        )

    assert first is sentinel
    assert second is None
    assert sched.call_count == 1


# ---------------------------------------------------------------------------
# 5-6. cycle fan-out
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_daily_cycle_fans_out():
    pool = MagicMock()
    slack = MagicMock()
    with patch(
        "hermes_agent.self_improvement.skill_scorer.run_for_all_tenants",
        new=AsyncMock(return_value=[{"tenant_id": "t1"}]),
    ) as scorer, patch(
        "hermes_agent.self_improvement.scheduling._all_tenant_ids",
        new=AsyncMock(return_value=["t1"]),
    ), patch(
        "hermes_agent.self_improvement.promotion_proposer.run_daily_proposer",
        new=AsyncMock(return_value={"dm_sent": True}),
    ) as promo, patch(
        "hermes_agent.self_improvement.drift_detector.run_for_all_tenants",
        new=AsyncMock(return_value=[{"tenant_id": "t1"}]),
    ) as drift:
        summary = await scheduling.run_daily_cycle(pool, slack)

    scorer.assert_awaited_once()
    promo.assert_awaited_once()
    drift.assert_awaited_once()
    assert summary["promotion"] == [{"dm_sent": True}]


@pytest.mark.asyncio
async def test_run_weekly_cycle_fans_out_per_tenant():
    pool = MagicMock()
    with patch(
        "hermes_agent.self_improvement.scheduling._all_tenant_ids",
        new=AsyncMock(return_value=["t1", "t2"]),
    ), patch(
        "hermes_agent.self_improvement.recommender.run_weekly_analysis",
        new=AsyncMock(return_value={"new_recommendations": 1}),
    ) as rec:
        summary = await scheduling.run_weekly_cycle(pool)

    assert rec.await_count == 2
    assert len(summary["recommendations"]) == 2


# ---------------------------------------------------------------------------
# 7-8. daily brief gate
# ---------------------------------------------------------------------------

# 2026-07-06 is a Monday; 2026-07-04 is a Saturday.
_MON_AM = datetime(2026, 7, 6, 8, 0, tzinfo=timezone.utc)
_MON_EARLY = datetime(2026, 7, 6, 6, 0, tzinfo=timezone.utc)
_SAT_AM = datetime(2026, 7, 4, 8, 0, tzinfo=timezone.utc)


def test_brief_skips_weekend(monkeypatch):
    monkeypatch.setenv("SLACK_DAILY_DM_CHANNEL", "D123")
    with patch("cron.daily_brief.run_daily_brief") as run:
        assert scheduling.maybe_run_daily_brief(now=_SAT_AM) is None
        run.assert_not_called()


def test_brief_skips_before_time(monkeypatch):
    monkeypatch.setenv("SLACK_DAILY_DM_CHANNEL", "D123")
    with patch("cron.daily_brief.run_daily_brief") as run:
        assert scheduling.maybe_run_daily_brief(now=_MON_EARLY) is None
        run.assert_not_called()


def test_brief_skips_without_channel(monkeypatch):
    monkeypatch.delenv("SLACK_DAILY_DM_CHANNEL", raising=False)
    monkeypatch.delenv("SLACK_HOME_CHANNEL", raising=False)
    with patch("cron.daily_brief.run_daily_brief") as run:
        assert scheduling.maybe_run_daily_brief(now=_MON_AM) is None
        run.assert_not_called()


def test_brief_fires_once_per_day(monkeypatch):
    monkeypatch.setenv("SLACK_DAILY_DM_CHANNEL", "D123")
    with patch(
        "cron.daily_brief.run_daily_brief",
        return_value={"status": "delivered"},
    ) as run:
        first = scheduling.maybe_run_daily_brief(now=_MON_AM)
        second = scheduling.maybe_run_daily_brief(
            now=_MON_AM + timedelta(hours=1)
        )

    assert first == {"status": "delivered"}
    assert second is None
    run.assert_called_once()
