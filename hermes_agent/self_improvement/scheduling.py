"""
Interval-gated activation seam for the Plan 004 self-improvement jobs.

The scoring / promotion / drift / recommendation jobs were shipped and
unit-tested in Plan 004, but nothing ever scheduled them — the daily and weekly
entrypoints were reachable only via the Forge HTTP endpoint, so in practice they
never ran autonomously. This module closes that gap the same way the Curator is
wired: the gateway cron ticker polls a cheap ``maybe_run_*`` function hourly, and
an internal last-run gate (persisted in a small state file, mirroring
``agent.curator``) fires the daily jobs roughly once a day and the weekly job
roughly once a week — resilient to poll jitter and gateway restarts.

Two independent entrypoints are exposed to the ticker:

* :func:`maybe_run_self_improvement` — the Neon-backed jobs (scoring, promotion
  DMs, drift alerts, weekly skill recommendations). These require the saas-mode
  asyncpg pool, whose coroutines must run on the gateway event loop, so the work
  is scheduled onto ``loop`` via :func:`safe_schedule_threadsafe`. When no pool
  is available (local / non-saas mode) the poll is a no-op, so wiring this into
  the ticker is safe in every deployment.

* :func:`maybe_run_daily_brief` — the weekday morning brief. Mode-agnostic
  (stdlib Slack post, no Neon), so it runs synchronously in the ticker thread
  behind a once-per-local-day guard.

Everything here is fail-soft: an exception in any job is logged and the last-run
timestamp is still advanced, so a broken job degrades to "skipped until the next
interval" rather than retrying every poll.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Cadence gates. Intervals are deliberately shorter than 24h/7d so that a
# gateway that restarts around the boundary still fires once per period instead
# of skipping a day. The ticker polls hourly, so the effective cadence is
# "first poll after the interval elapses".
DAILY_INTERVAL_HOURS = 20
WEEKLY_INTERVAL_HOURS = 24 * 6  # ~6 days
DEFAULT_BRIEF_HHMM = "07:30"


# ---------------------------------------------------------------------------
# Persistent state (mirrors agent.curator._state_file pattern)
# ---------------------------------------------------------------------------


def _state_file() -> Path:
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "self_improvement" / ".scheduler_state"


def _default_state() -> dict[str, Any]:
    return {
        "daily_last_run_at": None,
        "weekly_last_run_at": None,
        "brief_last_run_date": None,
    }


def _load_state() -> dict[str, Any]:
    path = _state_file()
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            merged = _default_state()
            merged.update(data)
            return merged
    except FileNotFoundError:
        pass
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("self-improvement: state read failed: %s", exc)
    return _default_state()


def _save_state(state: dict[str, Any]) -> None:
    path = _state_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), prefix=".scheduler_state_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):  # pragma: no cover - cleanup on rename success
                os.unlink(tmp)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("self-improvement: state write failed: %s", exc)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _is_due(last_iso: Optional[str], now: datetime, interval_hours: float) -> bool:
    """True when ``interval_hours`` has elapsed since ``last_iso`` (or it never ran)."""
    last = _parse_iso(last_iso)
    if last is None:
        return True
    return (now - last) >= timedelta(hours=interval_hours)


# ---------------------------------------------------------------------------
# Runtime handles (Neon pool + Slack client)
# ---------------------------------------------------------------------------


def _get_pool():
    """Return the saas-mode asyncpg pool, or None when unavailable.

    Mirrors ``SlackAdapter._get_neon_pool``: the jobs are Neon-backed, so in
    local / non-saas mode there is nothing to run and we no-op.
    """
    try:
        if os.environ.get("HERMES_MODE") != "saas":
            return None
        import hermes_storage as _hs

        backend = _hs._backend
        return getattr(backend, "_pool", None) if backend is not None else None
    except Exception:
        return None


def _make_slack_client():
    """Best-effort Slack AsyncWebClient for DM delivery (promotion / drift).

    Returns None when slack_sdk or the bot token is unavailable — the jobs
    accept ``slack_client=None`` and still persist their decisions to Neon.
    """
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        return None
    try:
        from slack_sdk.web.async_client import AsyncWebClient

        return AsyncWebClient(token=token)
    except Exception as exc:  # pragma: no cover - optional dep / import guard
        logger.debug("self-improvement: Slack client unavailable: %s", exc)
        return None


async def _all_tenant_ids(pool) -> list[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id FROM tenants")
    return [str(r["id"]) for r in rows]


# ---------------------------------------------------------------------------
# Job cycles (async; accept injected pool/slack_client so tests need no loop)
# ---------------------------------------------------------------------------


async def run_daily_cycle(pool, slack_client=None) -> dict[str, Any]:
    """Score skills, propose promotions (DM), and detect drift for all tenants."""
    from hermes_agent.self_improvement import (
        drift_detector,
        promotion_proposer,
        skill_scorer,
    )

    summary: dict[str, Any] = {}

    try:
        summary["scored"] = await skill_scorer.run_for_all_tenants(pool)
    except Exception as exc:
        logger.error("self-improvement: skill scoring failed: %s", exc)
        summary["scored_error"] = str(exc)

    promotion_results = []
    try:
        tenant_ids = await _all_tenant_ids(pool)
    except Exception as exc:
        logger.error("self-improvement: tenant enumeration failed: %s", exc)
        tenant_ids = []
    for tid in tenant_ids:
        try:
            promotion_results.append(
                await promotion_proposer.run_daily_proposer(
                    pool, tid, slack_client=slack_client
                )
            )
        except Exception as exc:
            logger.error("self-improvement: promotion proposer tenant=%s failed: %s", tid, exc)
            promotion_results.append({"tenant_id": tid, "error": str(exc)})
    summary["promotion"] = promotion_results

    try:
        summary["drift"] = await drift_detector.run_for_all_tenants(
            pool, slack_client=slack_client
        )
    except Exception as exc:
        logger.error("self-improvement: drift detection failed: %s", exc)
        summary["drift_error"] = str(exc)

    return summary


async def run_weekly_cycle(pool, slack_client=None) -> dict[str, Any]:
    """Weekly TF-IDF skill-gap analysis across all tenants."""
    from hermes_agent.self_improvement import recommender

    try:
        tenant_ids = await _all_tenant_ids(pool)
    except Exception as exc:
        logger.error("self-improvement: tenant enumeration failed: %s", exc)
        return {"recommendations": [], "error": str(exc)}

    recommendations = []
    for tid in tenant_ids:
        try:
            recommendations.append(await recommender.run_weekly_analysis(pool, tid))
        except Exception as exc:
            logger.error("self-improvement: recommender tenant=%s failed: %s", tid, exc)
            recommendations.append({"tenant_id": tid, "error": str(exc)})
    return {"recommendations": recommendations}


async def run_due_cycles(*, run_daily: bool, run_weekly: bool) -> dict[str, Any]:
    """Orchestrator scheduled onto the gateway loop. Acquires runtime handles."""
    pool = _get_pool()
    if pool is None:
        return {"skipped": "no_pool"}
    slack_client = _make_slack_client()
    result: dict[str, Any] = {}
    if run_daily:
        result["daily"] = await run_daily_cycle(pool, slack_client)
    if run_weekly:
        result["weekly"] = await run_weekly_cycle(pool, slack_client)
    return result


# ---------------------------------------------------------------------------
# Ticker entrypoints
# ---------------------------------------------------------------------------


def maybe_run_self_improvement(loop, now: Optional[datetime] = None):
    """Poll entrypoint for the Neon-backed jobs. Safe to call every tick.

    Returns the scheduled ``concurrent.futures.Future`` when a cycle was
    dispatched, else None (nothing due, or no saas pool available).
    """
    from agent.async_utils import safe_schedule_threadsafe

    now = now or datetime.now(timezone.utc)
    state = _load_state()
    run_daily = _is_due(state.get("daily_last_run_at"), now, DAILY_INTERVAL_HOURS)
    run_weekly = _is_due(state.get("weekly_last_run_at"), now, WEEKLY_INTERVAL_HOURS)
    if not (run_daily or run_weekly):
        return None

    # Cheap guard: don't churn the event loop in local/non-saas mode.
    if _get_pool() is None:
        return None

    fut = safe_schedule_threadsafe(
        run_due_cycles(run_daily=run_daily, run_weekly=run_weekly),
        loop,
        logger=logger,
        log_message="self-improvement cycle scheduling error",
    )
    if fut is None:
        return None

    # Advance the gate now (fail-forward): a broken job degrades to
    # "skipped until next interval" instead of retrying every poll.
    if run_daily:
        state["daily_last_run_at"] = now.isoformat()
    if run_weekly:
        state["weekly_last_run_at"] = now.isoformat()
    _save_state(state)
    logger.info(
        "self-improvement: dispatched cycle (daily=%s weekly=%s)", run_daily, run_weekly
    )
    return fut


def _brief_time() -> tuple[int, int]:
    raw = os.environ.get("SLACK_DAILY_BRIEF_HHMM", DEFAULT_BRIEF_HHMM)
    try:
        hh, mm = raw.split(":", 1)
        return int(hh), int(mm)
    except Exception:
        return 7, 30


def maybe_run_daily_brief(now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """Poll entrypoint for the weekday morning brief. Runs at most once/local-day.

    Fires when: it's a weekday, local time is at/after the configured brief time,
    a Slack DM/home channel is configured, and no brief has been sent today.
    Runs synchronously (stdlib Slack post) in the ticker thread.
    """
    from cron.daily_brief import WEEKDAY_GATE, _now_user_local, run_daily_brief

    local = _now_user_local(now)
    if local.weekday() not in WEEKDAY_GATE:
        return None

    hh, mm = _brief_time()
    if (local.hour, local.minute) < (hh, mm):
        return None

    if not (
        os.environ.get("SLACK_DAILY_DM_CHANNEL")
        or os.environ.get("SLACK_HOME_CHANNEL")
    ):
        # No delivery target configured — skip silently rather than fail every poll.
        return None

    today = local.strftime("%Y-%m-%d")
    state = _load_state()
    if state.get("brief_last_run_date") == today:
        return None

    try:
        result = run_daily_brief(now=now)
    except Exception as exc:
        logger.warning("self-improvement: daily brief failed: %s", exc)
        result = {"status": "failed", "reason": str(exc)}

    # Mark today done regardless of outcome so a transient failure doesn't
    # re-fire every 5 minutes for the rest of the day.
    state["brief_last_run_date"] = today
    _save_state(state)
    logger.info("self-improvement: daily brief status=%s", result.get("status"))
    return result
