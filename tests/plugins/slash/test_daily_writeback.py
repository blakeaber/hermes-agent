"""Unit tests for Plan 026-B — AgentDecision write-back + reaction harvest.

Acceptance criteria mapped to test functions:

AC1 — After a brief sends, the AgentDecision triple is written to Atlas.
      Covered by ``test_write_agent_decision_writes_through_writer`` +
      ``test_build_daily_brief_writes_back_after_synthesis``.

AC2 — Reaction states surface on the triple after the 12h harvest cycle.
      Covered by ``test_schedule_reaction_harvest_runs_after_delay`` +
      ``test_harvest_writes_reaction_states_back``.

AC3 — Tomorrow's brief contains a "yesterday you acted on X" prologue
      when Atlas returns one. Covered by
      ``test_build_blocks_renders_yesterday_prologue`` +
      ``test_gather_brief_includes_prologue_when_atlas_returns_one``.

AC4 — Idempotency: re-running the write-back for the same brief is a
      no-op. Covered by ``test_write_agent_decision_is_idempotent``.

AC5 — 5+ new tests covering write + read-back. This file contains 12.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from plugins.slash import daily as daily_mod
from plugins.slash import daily_writeback as wb
from plugins.slash.daily import (
    BriefBundle,
    DailyHandlerConfig,
    SourceResult,
    build_blocks,
    build_daily_brief,
    synthesize_bullets,
)
from plugins.slash.daily_writeback import (
    AgentDecisionRecord,
    REACTION_STATE_MAP,
    build_decision_record,
    fetch_yesterday_prologue,
    harvest_reactions,
    map_reactions_to_states,
    mint_decision_urn,
    schedule_reaction_harvest,
    write_agent_decision,
)


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_writeback_cache():
    """Each test starts with a clean in-process idempotency set."""
    wb._reset_written_for_tests()
    yield
    wb._reset_written_for_tests()


class _RecordingWriter:
    """Atlas writer that records every call instead of hitting HTTP."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, target: str, content: str) -> None:
        self.calls.append((target, content))


def _bundle(**overrides) -> BriefBundle:
    defaults = dict(
        calendar=SourceResult("calendar", "ok", ("9am intro",), ("https://cal/1",)),
        inbox=SourceResult("inbox", "empty"),
        commitments=SourceResult("commitments", "ok", ("Email Greg",), ("urn:atlas:chunk:c1",)),
        contradictions=SourceResult("contradictions", "empty"),
        contacts_overdue=SourceResult("contacts_overdue", "empty"),
        orchestrator=SourceResult("orchestrator", "empty"),
        elapsed_secs=0.1,
    )
    defaults.update(overrides)
    return BriefBundle(**defaults)


# ---------------------------------------------------------------------------
# URN minting
# ---------------------------------------------------------------------------


def test_mint_decision_urn_is_deterministic():
    a = mint_decision_urn("dm:bossman2", "1717000000.000100")
    b = mint_decision_urn("dm:bossman2", "1717000000.000100")
    assert a == b
    assert a.startswith("urn:atlas:agent_decision:slack:")
    assert "dm_bossman2" in a
    assert "1717000000.000100" in a


def test_mint_decision_urn_differs_per_message():
    a = mint_decision_urn("dm:bossman2", "1.0")
    b = mint_decision_urn("dm:bossman2", "2.0")
    assert a != b


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------


def test_build_decision_record_collects_bullets_and_dedup_citations():
    bullets = (
        ("commitments", "Email Greg", ("urn:atlas:chunk:c1", "urn:atlas:chunk:c2")),
        ("calendar", "9am intro", ("urn:atlas:chunk:c1",)),  # duplicate cite
    )
    rec = build_decision_record(
        bullets=bullets,
        slack_channel="dm:bossman2",
        slack_message_ts="1717.0001",
    )
    assert rec.bullets == (
        ("commitments", "Email Greg"),
        ("calendar", "9am intro"),
    )
    # Duplicate citation dropped; order preserved.
    assert rec.citations == ("urn:atlas:chunk:c1", "urn:atlas:chunk:c2")
    assert rec.slack_message_ts == "1717.0001"
    assert rec.reaction_states == ()
    assert rec.urn == mint_decision_urn("dm:bossman2", "1717.0001")


def test_decision_record_to_content_round_trips_json():
    rec = build_decision_record(
        bullets=(("commitments", "Email Greg", ("urn:atlas:chunk:c1",)),),
        slack_message_ts="1.2",
    )
    content = rec.to_content()
    assert content.startswith("[AgentDecision] ")
    body = json.loads(content[len("[AgentDecision] "):])
    assert body["type"] == "atlas:AgentDecision"
    assert body["urn"] == rec.urn
    assert body["bullets"] == [{"source": "commitments", "text": "Email Greg"}]
    assert body["citations"] == ["urn:atlas:chunk:c1"]
    assert body["reaction_states"] == []
    assert body["source"] == "/daily"


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def test_write_agent_decision_writes_through_writer():
    rec = build_decision_record(
        bullets=(("commitments", "Email Greg", ("urn:atlas:chunk:c1",)),),
        slack_message_ts="9.0",
    )
    writer = _RecordingWriter()
    ok = write_agent_decision(rec, atlas_writer=writer)
    assert ok is True
    assert len(writer.calls) == 1
    target, content = writer.calls[0]
    assert target == "memory"
    assert content.startswith("[AgentDecision] ")
    assert rec.urn in content


def test_write_agent_decision_is_idempotent():
    """AC4 — re-running the write for the same URN is a no-op."""
    rec = build_decision_record(
        bullets=(("commitments", "X", ()),), slack_message_ts="42.0",
    )
    writer = _RecordingWriter()
    write_agent_decision(rec, atlas_writer=writer)
    write_agent_decision(rec, atlas_writer=writer)
    write_agent_decision(rec, atlas_writer=writer)
    # Only the first call hits the writer; subsequent are short-circuited.
    assert len(writer.calls) == 1


def test_write_agent_decision_swallows_writer_errors():
    """The brief must still post if Atlas is down."""
    rec = build_decision_record(
        bullets=(("commitments", "X", ()),), slack_message_ts="13.0",
    )

    def _boom(target, content):
        raise RuntimeError("atlas 503")

    ok = write_agent_decision(rec, atlas_writer=_boom)
    assert ok is False
    # The failed write is NOT cached, so a retry would be allowed.
    assert rec.urn not in wb._written_urns_for_tests()


# ---------------------------------------------------------------------------
# Reaction mapping
# ---------------------------------------------------------------------------


def test_map_reactions_to_states_picks_dominant_recognized_emoji():
    reactions = [
        {"name": "tada", "count": 5},  # unrecognized, ignored
        {"name": "large_green_circle", "count": 1},
        {"name": "large_red_circle", "count": 3},  # dominant recognized
    ]
    states = map_reactions_to_states(reactions, bullet_keys=("commitments", "calendar"))
    assert states == (("commitments", "dismissed"), ("calendar", "dismissed"))


def test_map_reactions_to_states_returns_empty_when_no_recognized_emoji():
    reactions = [{"name": "tada", "count": 99}]
    states = map_reactions_to_states(reactions, bullet_keys=("commitments",))
    assert states == ()


def test_map_reactions_to_states_handles_colon_wrapping():
    """Slack sometimes returns ":name:" rather than "name"."""
    reactions = [{"name": ":green_circle:", "count": 2}]
    states = map_reactions_to_states(reactions, bullet_keys=("commitments",))
    assert states == (("commitments", "acted_on"),)


# ---------------------------------------------------------------------------
# Harvester
# ---------------------------------------------------------------------------


def test_harvest_writes_reaction_states_back():
    rec = build_decision_record(
        bullets=(("commitments", "Email Greg", ("urn:atlas:chunk:c1",)),),
        slack_message_ts="100.0",
    )
    writer = _RecordingWriter()

    async def _fake_fetch(channel, ts):
        assert ts == "100.0"
        return [{"name": "large_green_circle", "count": 1}]

    updated = asyncio.run(harvest_reactions(
        rec, slack_reaction_fetcher=_fake_fetch, atlas_writer=writer,
    ))
    assert updated.reaction_states == (("commitments", "acted_on"),)
    # Same URN → Atlas-side dedup handles the update; we still re-write.
    assert updated.urn == rec.urn
    assert len(writer.calls) == 1
    # Content reflects the new state.
    body = json.loads(writer.calls[0][1][len("[AgentDecision] "):])
    assert body["reaction_states"] == [{"source": "commitments", "state": "acted_on"}]


def test_harvest_degrades_gracefully_on_slack_failure():
    rec = build_decision_record(
        bullets=(("commitments", "x", ()),), slack_message_ts="200.0",
    )
    writer = _RecordingWriter()

    async def _broken_fetch(channel, ts):
        raise RuntimeError("rate limited")

    updated = asyncio.run(harvest_reactions(
        rec, slack_reaction_fetcher=_broken_fetch, atlas_writer=writer,
    ))
    # No reactions captured; still rewrites with empty states so the
    # Atlas side knows the harvest ran.
    assert updated.reaction_states == ()
    assert len(writer.calls) == 1


def test_schedule_reaction_harvest_runs_after_delay():
    """AC2 — the harvest runs at the scheduled delay, mockable to 0s."""
    rec = build_decision_record(
        bullets=(("commitments", "x", ()),), slack_message_ts="300.0",
    )
    writer = _RecordingWriter()
    sleep_calls: list[float] = []

    async def _instant_sleep(delay):
        sleep_calls.append(delay)
        # Don't actually sleep; just yield so the loop can progress.
        await asyncio.sleep(0)

    async def _fake_fetch(channel, ts):
        return [{"name": "white_circle", "count": 1}]

    async def _run():
        task = schedule_reaction_harvest(
            rec,
            slack_reaction_fetcher=_fake_fetch,
            atlas_writer=writer,
            delay_secs=43200.0,
            sleeper=_instant_sleep,
        )
        return await task

    updated = asyncio.run(_run())
    # The sleeper was called with the 12h delay (43200s) — the cron
    # cadence the master plan specified.
    assert sleep_calls == [43200.0]
    assert updated.reaction_states == (("commitments", "deferred"),)
    assert len(writer.calls) == 1


def test_default_harvest_delay_is_twelve_hours():
    assert wb.DEFAULT_HARVEST_DELAY_SECS == 12 * 60 * 60


# ---------------------------------------------------------------------------
# Yesterday prologue read-back
# ---------------------------------------------------------------------------


def test_fetch_yesterday_prologue_returns_first_sentence():
    async def _ask(question, hint):
        assert hint == "decision_followup"
        return {
            "answer": "You acted on Greg's outreach yesterday but deferred Sarah.\nMore detail follows.",
            "citations": [],
        }

    prologue = asyncio.run(fetch_yesterday_prologue(atlas_ask=_ask))
    assert prologue == "You acted on Greg's outreach yesterday but deferred Sarah."


def test_fetch_yesterday_prologue_returns_none_on_empty():
    async def _ask(q, h):
        return {"answer": "", "citations": []}

    assert asyncio.run(fetch_yesterday_prologue(atlas_ask=_ask)) is None


def test_fetch_yesterday_prologue_returns_none_on_error_payload():
    async def _ask(q, h):
        return {"error": "breaker open"}

    assert asyncio.run(fetch_yesterday_prologue(atlas_ask=_ask)) is None


def test_fetch_yesterday_prologue_returns_none_on_exception():
    async def _ask(q, h):
        raise RuntimeError("boom")

    assert asyncio.run(fetch_yesterday_prologue(atlas_ask=_ask)) is None


def test_build_blocks_renders_yesterday_prologue():
    """AC3 — prologue surfaces as a context block under the header."""
    bundle = _bundle(yesterday_prologue="You acted on Greg, deferred Sarah.")
    payload = build_blocks(bundle)
    # header + prologue context + top-line section + divider + 6 sources + footer
    assert len(payload["blocks"]) == 11
    assert payload["blocks"][0]["type"] == "header"
    assert payload["blocks"][1]["type"] == "context"
    assert "Yesterday" in payload["blocks"][1]["elements"][0]["text"]
    assert "acted on Greg" in payload["blocks"][1]["elements"][0]["text"]


def test_build_blocks_omits_prologue_when_none():
    """When no prologue is available, block count is unchanged from 026-A."""
    bundle = _bundle(yesterday_prologue=None)
    payload = build_blocks(bundle)
    assert len(payload["blocks"]) == 10  # the original 026-A shape


# ---------------------------------------------------------------------------
# End-to-end through build_daily_brief
# ---------------------------------------------------------------------------


def test_build_daily_brief_writes_back_after_synthesis():
    """AC1 — build_daily_brief writes one AgentDecision to Atlas."""

    async def _atlas_ask(q, hint):
        if hint == "commitment_audit":
            return {"answer": "Email Greg", "citations": [{"chunk_id": "c1"}]}
        return {"answer": "", "citations": []}

    async def _cal():
        return SourceResult("calendar", "empty")

    async def _inbox():
        return SourceResult("inbox", "empty")

    writer = _RecordingWriter()
    cfg = DailyHandlerConfig(
        atlas_ask=_atlas_ask,
        calendar_fetcher=_cal,
        inbox_fetcher=_inbox,
        orchestrator_base_url="",
        atlas_writer=writer,
        slack_message_ts="9999.0001",
        slack_channel="dm:bossman2",
    )
    payload = asyncio.run(build_daily_brief(cfg))

    # One AgentDecision triple landed.
    assert len(writer.calls) == 1
    target, content = writer.calls[0]
    assert target == "memory"
    body = json.loads(content[len("[AgentDecision] "):])
    assert body["type"] == "atlas:AgentDecision"
    assert body["slack_message_ts"] == "9999.0001"
    assert body["bullets"] == [{"source": "commitments", "text": "✅ Commitments — Email Greg"}]
    # Brief payload exposes the URN for downstream tracing.
    assert payload["_daily_meta"]["agent_decision_urn"] == body["urn"]


def test_build_daily_brief_writeback_disabled_skips_atlas():
    async def _ask(q, h):
        return {"answer": "", "citations": []}

    writer = _RecordingWriter()
    cfg = DailyHandlerConfig(
        atlas_ask=_ask,
        calendar_fetcher=lambda: _async_empty("calendar"),
        inbox_fetcher=lambda: _async_empty("inbox"),
        orchestrator_base_url="",
        writeback_enabled=False,
        atlas_writer=writer,
    )
    payload = asyncio.run(build_daily_brief(cfg))
    assert writer.calls == []
    assert "_daily_meta" not in payload


async def _async_empty(key):
    return SourceResult(key, "empty")


def test_build_daily_brief_schedules_harvest_when_fetcher_provided():
    async def _ask(q, h):
        if h == "commitment_audit":
            return {"answer": "Email Greg", "citations": [{"chunk_id": "c1"}]}
        return {"answer": "", "citations": []}

    writer = _RecordingWriter()
    fetch_calls: list[tuple[str, str]] = []

    async def _fake_slack(channel, ts):
        fetch_calls.append((channel, ts))
        return [{"name": "large_green_circle", "count": 1}]

    async def _instant_sleep(delay):
        await asyncio.sleep(0)

    async def _run():
        cfg = DailyHandlerConfig(
            atlas_ask=_ask,
            calendar_fetcher=lambda: _async_empty("calendar"),
            inbox_fetcher=lambda: _async_empty("inbox"),
            orchestrator_base_url="",
            atlas_writer=writer,
            slack_reaction_fetcher=_fake_slack,
            slack_message_ts="harvest.0001",
            harvest_sleeper=_instant_sleep,
            harvest_delay_secs=0.0,
        )
        payload = await build_daily_brief(cfg)
        # Wait for the harvest task to complete so the writeback lands.
        # We do this by yielding to the event loop a couple of times.
        for _ in range(10):
            await asyncio.sleep(0)
            if len(writer.calls) >= 2:
                break
        return payload

    payload = asyncio.run(_run())

    assert payload["_daily_meta"]["agent_decision_urn"]
    assert "harvest_task" in payload["_daily_meta"]
    # The harvest ran end-to-end: Slack fetch + Atlas re-write.
    assert fetch_calls == [("dm:bossman2", "harvest.0001")]
    assert len(writer.calls) == 2  # initial + harvest update
    second_body = json.loads(writer.calls[1][1][len("[AgentDecision] "):])
    assert second_body["reaction_states"] == [
        {"source": "commitments", "state": "acted_on"}
    ]


def test_gather_brief_includes_prologue_when_atlas_returns_one():
    """AC3 — the fan-out picks up the prologue alongside the source results."""

    async def _ask(q, hint):
        if hint == "decision_followup":
            return {"answer": "Acted on Greg.", "citations": []}
        return {"answer": "", "citations": []}

    async def _empty_cal():
        return SourceResult("calendar", "empty")

    async def _empty_inbox():
        return SourceResult("inbox", "empty")

    bundle = asyncio.run(daily_mod._gather_brief(
        atlas_ask=_ask,
        calendar_fetcher=_empty_cal,
        inbox_fetcher=_empty_inbox,
        orchestrator_base_url="",
    ))
    assert bundle.yesterday_prologue == "Acted on Greg."


def test_gather_brief_skips_prologue_when_disabled():
    async def _ask(q, hint):
        return {"answer": "Acted on Greg.", "citations": []}

    bundle = asyncio.run(daily_mod._gather_brief(
        atlas_ask=_ask,
        calendar_fetcher=lambda: _async_empty("calendar"),
        inbox_fetcher=lambda: _async_empty("inbox"),
        orchestrator_base_url="",
        fetch_prologue=False,
    ))
    assert bundle.yesterday_prologue is None


# ---------------------------------------------------------------------------
# REACTION_STATE_MAP covers the three documented states
# ---------------------------------------------------------------------------


def test_reaction_state_map_covers_three_action_states():
    states = set(REACTION_STATE_MAP.values())
    assert states == {"acted_on", "dismissed", "deferred"}
