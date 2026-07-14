"""AgentDecision write-back + 12h reaction harvest — Plan 026-B.

The /daily plugin (026-A) builds a 3-bullet brief and returns it as a
Slack block-kit payload. Per master plan §"Phase 026-B", we close the
behavioral loop by:

1. **Synchronous write at brief send.** Immediately after the brief
   posts (or is built, in the cron path), we persist one
   ``atlas:AgentDecision`` triple to ``urn:atlas:graph:events`` so
   tomorrow's brief can synthesize "what did Blake act on yesterday?"
   from yesterday's bullets × today's reactions × Linear/Pipedrive
   state diffs.

2. **Delayed reaction harvest.** 12 hours later, we poll Slack's
   ``reactions.get`` API for the brief message, map emojis to action
   states (🟢 acted_on / 🔴 dismissed / ⚪ deferred), and write back a
   second ``atlas:reaction`` predicate per bullet on the same
   ``AgentDecision`` URN.

The write goes through the existing ``AtlasMemoryProvider._write_fact``
shim (POST ``/v1/memory/hermes/write``) — there is no new Atlas
endpoint and no new bearer/auth path. The content payload is a
structured turtle-like serialization of the triple; the Atlas-side
typed-entity expansion (Plan 015 / 025-C ``AgentDecision`` type) parses
it back into RDF.

**Idempotency.** The AgentDecision URN is derived from the Slack
message_ts (``urn:atlas:agent_decision:slack:<channel>:<ts>``), so
re-running the write-back for the same brief is a no-op at the Atlas
layer. We also short-circuit in the writer when the same URN is seen
twice in-process.

**Failure semantics.** Per the user memory note "honest failure
semantics" — the write-back is best-effort. If Atlas is down the
brief still posts and we log the failure; we don't fail the slash
command. The 12h harvest is similarly best-effort: a missed harvest
just means tomorrow's prologue won't include yesterday's reaction
states. The brief itself still synthesizes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Sequence

logger = logging.getLogger(__name__)


# 12 hours after the brief sends. Reactions accumulated by lunch /
# early afternoon are a reasonable proxy for "did Blake act on this?".
# Per the master plan a 12h cadence is the explicit harvest window.
DEFAULT_HARVEST_DELAY_SECS = 12 * 60 * 60  # 12h

# Slack-side emoji → action state mapping. Matches the master plan's
# reaction taxonomy (🟢/🔴/⚪) and adds the two synonyms Slack ships
# for the green/red circles out of the box.
REACTION_STATE_MAP: dict[str, str] = {
    "large_green_circle": "acted_on",
    "green_circle": "acted_on",
    "white_check_mark": "acted_on",
    "large_red_circle": "dismissed",
    "red_circle": "dismissed",
    "x": "dismissed",
    "white_circle": "deferred",
    "hourglass_flowing_sand": "deferred",
    "clock1": "deferred",
}


# ---------------------------------------------------------------------------
# Record shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentDecisionRecord:
    """One ``atlas:AgentDecision`` triple, pre-serialization.

    ``urn`` is the deterministic identity — same Slack message → same
    URN → idempotent Atlas writes.

    ``bullets`` is the list of ``(source_key, text)`` from
    ``synthesize_bullets``. We deliberately don't carry the block-kit
    JSON: the bullets are the operator-facing decision surface, and
    tomorrow's synthesizer needs them as plain text to render
    "yesterday you saw: X / Y / Z, and acted on X".

    ``citations`` is a flat tuple of all citation IRIs across bullets;
    de-duplicated. The follow-up reasoning ("what did Blake act on?")
    needs to be able to resolve the citation IRIs back through
    ``/v1/ask`` to see the underlying source.

    ``reaction_states`` is empty at sync-write time and filled in by
    the 12h harvest job. The harvester writes a *second* record with
    the same URN — the Atlas typed-entity store handles the replace
    semantics on its end.
    """

    urn: str
    timestamp: str           # ISO-8601 UTC at brief-send time
    slack_channel: str
    slack_message_ts: str
    bullets: tuple[tuple[str, str], ...]      # (source_key, text)
    citations: tuple[str, ...]
    reaction_states: tuple[tuple[str, str], ...] = ()  # (source_key, state)

    def to_content(self) -> str:
        """Render the record as Atlas-write content.

        Atlas's typed-entity expansion (Plan 015 / 025-C) accepts a
        structured JSON content blob and converts it into RDF triples.
        We tag the type with ``atlas:AgentDecision`` so the typed
        expander on the Atlas side dispatches to the right schema.

        We pass JSON (not raw turtle) because the existing
        ``/v1/memory/hermes/write`` route accepts free-text content; the
        Atlas side has dedicated handlers for content beginning with
        ``[AgentDecision]`` (per the 015 typed-entity convention).
        """
        body = {
            "type": "atlas:AgentDecision",
            "urn": self.urn,
            "timestamp": self.timestamp,
            "source": "/daily",
            "slack_channel": self.slack_channel,
            "slack_message_ts": self.slack_message_ts,
            "bullets": [
                {"source": k, "text": t} for k, t in self.bullets
            ],
            "citations": list(self.citations),
            "reaction_states": [
                {"source": k, "state": s} for k, s in self.reaction_states
            ],
        }
        return f"[AgentDecision] {json.dumps(body, separators=(',', ':'))}"


# ---------------------------------------------------------------------------
# URN minting
# ---------------------------------------------------------------------------


def mint_decision_urn(channel: str, message_ts: str) -> str:
    """Deterministic AgentDecision URN.

    Slack's ``message_ts`` is monotonically unique per channel, so the
    pair ``(channel, ts)`` is a stable identity. Sanitize colons /
    slashes in the channel so the URN survives downstream IRI parsers
    that don't handle nested ``:`` well.
    """
    safe_chan = (channel or "unknown").replace("/", "_").replace(":", "_")
    safe_ts = (message_ts or "0").replace("/", "_")
    return f"urn:atlas:agent_decision:slack:{safe_chan}:{safe_ts}"


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------


def build_decision_record(
    *,
    bullets: Sequence[tuple[str, str, tuple[str, ...]]],
    slack_channel: str = "dm:bossman2",
    slack_message_ts: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> AgentDecisionRecord:
    """Construct the AgentDecisionRecord from the synthesizer output.

    ``bullets`` is the return shape of ``daily.synthesize_bullets`` —
    a tuple of ``(source_key, text, citations)``.

    ``slack_message_ts`` defaults to ``str(time.time())`` for callers
    that don't have a real Slack message_ts yet (e.g. unit tests, or
    the cron path before the post has happened). The downside is the
    URN won't match the eventually-posted message, so the harvester
    won't find the right reactions. The slash-command path patches
    the URN with the real message_ts via ``update_message_ts`` once
    Slack returns the post receipt.
    """
    ts = timestamp or _now_iso()
    msg_ts = slack_message_ts or str(int(time.time() * 1000))
    urn = mint_decision_urn(slack_channel, msg_ts)

    bullet_pairs: list[tuple[str, str]] = []
    citations: list[str] = []
    seen_cites: set[str] = set()
    for entry in bullets:
        if not entry:
            continue
        # Synthesizer shape is (key, text, citations); be permissive.
        key = entry[0]
        text = entry[1] if len(entry) > 1 else ""
        cites = entry[2] if len(entry) > 2 else ()
        bullet_pairs.append((key, text))
        for c in cites or ():
            if c and c not in seen_cites:
                seen_cites.add(c)
                citations.append(c)

    return AgentDecisionRecord(
        urn=urn,
        timestamp=ts,
        slack_channel=slack_channel,
        slack_message_ts=msg_ts,
        bullets=tuple(bullet_pairs),
        citations=tuple(citations),
    )


def _now_iso() -> str:
    """UTC ISO-8601 timestamp with second resolution.

    Module-local helper so tests can monkeypatch a deterministic clock.
    """
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


AtlasWriter = Callable[[str, str], None]
"""``atlas_writer(target, content)`` — best-effort writer.

In production the writer wraps ``AtlasMemoryProvider._write_fact`` with
``target="memory"`` (the AgentDecision lives in the events graph, not
the user-facts graph). For tests, callers inject a fake that records
calls.
"""


# In-process idempotency cache. A single Hermes process should never
# write the same AgentDecision twice (e.g. on retry). Bounded to the
# last 256 URNs — enough for a week of /daily fires + some manual
# tests.
_WRITTEN_URNS: list[str] = []
_WRITTEN_URN_CAP = 256


def _remember_written(urn: str) -> None:
    _WRITTEN_URNS.append(urn)
    if len(_WRITTEN_URNS) > _WRITTEN_URN_CAP:
        del _WRITTEN_URNS[: len(_WRITTEN_URNS) - _WRITTEN_URN_CAP]


def _reset_written_for_tests() -> None:
    """Tests call this in setup to start with a clean idempotency set."""
    _WRITTEN_URNS.clear()


def write_agent_decision(
    record: AgentDecisionRecord,
    *,
    atlas_writer: Optional[AtlasWriter] = None,
) -> bool:
    """Persist the AgentDecision triple to Atlas.

    Returns ``True`` on a successful (or short-circuited) write,
    ``False`` if Atlas raised. Never raises — the brief must still post
    if Atlas is down.

    ``atlas_writer`` defaults to a thin wrapper around
    ``AtlasMemoryProvider._write_fact``. Tests inject a fake.
    """
    if record.urn in _WRITTEN_URNS:
        logger.info("[daily.writeback] skip duplicate urn=%s", record.urn)
        return True

    writer = atlas_writer or _default_atlas_writer
    try:
        writer("memory", record.to_content())
        _remember_written(record.urn)
        logger.info("[daily.writeback] wrote urn=%s bullets=%d", record.urn, len(record.bullets))
        return True
    except Exception as exc:
        logger.warning("[daily.writeback] write failed urn=%s err=%s", record.urn, exc)
        return False


def _default_atlas_writer(target: str, content: str) -> None:
    """Real writer — defers the import so unit tests don't pay the cost.

    Uses ``AtlasMemoryProvider._write_fact`` so we inherit bearer auth,
    breaker, and config-loading for free. If the provider isn't
    available (Atlas memory disabled in this Hermes install), we
    silently no-op — the brief still posts and the user sees a degraded
    "no decision write-back" log line.
    """
    try:
        from plugins.memory.atlas import AtlasMemoryProvider  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised in integration
        logger.info("[daily.writeback] atlas memory provider unavailable: %s", exc)
        return

    provider = AtlasMemoryProvider()
    if not provider.is_available():
        logger.info("[daily.writeback] atlas provider not configured; skipping write")
        return

    provider._write_fact(target=target, action="add", content=content)


# ---------------------------------------------------------------------------
# Reaction harvester
# ---------------------------------------------------------------------------


SlackReactionFetcher = Callable[[str, str], Awaitable[list[dict]]]
"""``fetch(channel, ts) -> [{name, count, users}, ...]``.

Wraps Slack's ``reactions.get`` API. Tests inject a fake that returns
a canned reaction list without hitting the network.
"""


def map_reactions_to_states(
    reactions: Sequence[dict],
    *,
    bullet_keys: Sequence[str],
) -> tuple[tuple[str, str], ...]:
    """Translate raw Slack reactions into per-bullet action states.

    Slack's ``reactions.get`` response lists each reaction emoji once
    with a count and the users who reacted. The brief carries 1-3
    bullets, and Blake's reactions in v1 apply to *the whole brief*
    (not per-bullet — Slack doesn't surface reaction-per-bullet on a
    block-kit message; only the message as a whole). So we apply the
    same dominant state to all bullets, picked by the most-recent /
    most-frequent recognized reaction.

    Algorithm:
      1. Filter to emojis we recognize in ``REACTION_STATE_MAP``.
      2. Sort by count desc; the top recognized reaction wins.
      3. Apply that state to every bullet. Unrecognized reactions are
         ignored (Blake can still 🎉 the brief without it confusing
         the next-day synthesis).
      4. If no recognized reaction is present, return ``()`` — the
         "deferred" state is *intentional*, not "no reaction".

    Returns a tuple of ``(source_key, state)`` aligned with
    ``bullet_keys``.
    """
    recognized: list[tuple[str, int]] = []
    for r in reactions or ():
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "").lstrip(":").rstrip(":")
        count = int(r.get("count") or 0)
        if name in REACTION_STATE_MAP and count > 0:
            recognized.append((name, count))

    if not recognized:
        return ()

    recognized.sort(key=lambda x: x[1], reverse=True)
    top_state = REACTION_STATE_MAP[recognized[0][0]]
    return tuple((k, top_state) for k in bullet_keys)


async def harvest_reactions(
    record: AgentDecisionRecord,
    *,
    slack_reaction_fetcher: SlackReactionFetcher,
    atlas_writer: Optional[AtlasWriter] = None,
) -> AgentDecisionRecord:
    """Poll Slack reactions and write back the updated record.

    Returns the new ``AgentDecisionRecord`` with ``reaction_states``
    filled in. Caller can inspect it (mainly for tests); production
    callers don't usually use the return value.

    Non-raising. Slack-side failures degrade to "no reactions yet" /
    empty state and re-write with empty ``reaction_states`` (the
    Atlas side preserves the original URN; the empty update is a
    no-op signal that the harvest ran).
    """
    try:
        reactions = await slack_reaction_fetcher(record.slack_channel, record.slack_message_ts)
    except Exception as exc:
        logger.warning(
            "[daily.harvest] slack reactions fetch failed urn=%s err=%s",
            record.urn, exc,
        )
        reactions = []

    bullet_keys = [k for k, _t in record.bullets]
    states = map_reactions_to_states(reactions, bullet_keys=bullet_keys)

    updated = AgentDecisionRecord(
        urn=record.urn,
        timestamp=record.timestamp,
        slack_channel=record.slack_channel,
        slack_message_ts=record.slack_message_ts,
        bullets=record.bullets,
        citations=record.citations,
        reaction_states=states,
    )

    # Re-write: the URN is the same so Atlas-side updates the existing
    # entity rather than minting a duplicate. We bypass the in-process
    # idempotency cache for harvest writes because the *content* is
    # different — the cache exists to prevent duplicate-original writes,
    # not to block legitimate updates.
    writer = atlas_writer or _default_atlas_writer
    try:
        writer("memory", updated.to_content())
        logger.info(
            "[daily.harvest] wrote reactions urn=%s states=%s",
            updated.urn, dict(updated.reaction_states),
        )
    except Exception as exc:
        logger.warning("[daily.harvest] atlas write failed urn=%s err=%s", updated.urn, exc)

    return updated


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def schedule_reaction_harvest(
    record: AgentDecisionRecord,
    *,
    slack_reaction_fetcher: SlackReactionFetcher,
    atlas_writer: Optional[AtlasWriter] = None,
    delay_secs: float = DEFAULT_HARVEST_DELAY_SECS,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> "asyncio.Task[AgentDecisionRecord]":
    """Schedule the 12h delayed harvest as an in-memory asyncio task.

    Why in-memory and not via ``cron/scheduler.py``: the Hermes cron
    scheduler is for user-defined recurring agent runs (per Plan 027
    scheduling contract), with full toolset / profile config and
    injection scanning. The reaction harvest is a *single-channel,
    single-shot, internal* polling step — it has no LLM exposure and
    doesn't fit the cron-job shape. We schedule it as an asyncio task
    on the existing slash-handler event loop.

    The ``sleeper`` is injectable so tests can run the schedule with
    zero delay and still exercise the harvest path. In production the
    default ``asyncio.sleep`` honours the full 12h window.

    Returns the scheduled task so callers can await it (tests do this
    to assert on the post-harvest state).
    """
    async def _delayed_harvest() -> AgentDecisionRecord:
        try:
            await sleeper(delay_secs)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[daily.harvest] sleep failed urn=%s err=%s", record.urn, exc)
        return await harvest_reactions(
            record,
            slack_reaction_fetcher=slack_reaction_fetcher,
            atlas_writer=atlas_writer,
        )

    return asyncio.create_task(_delayed_harvest(), name=f"daily-harvest-{record.urn}")


# ---------------------------------------------------------------------------
# Yesterday's-decision read-back (for tomorrow's prologue)
# ---------------------------------------------------------------------------


YESTERDAY_PROLOGUE_QUESTION = (
    "What action items from yesterday's /daily brief did I act on, "
    "based on Slack reactions and Linear/Pipedrive state changes?"
)
YESTERDAY_PROLOGUE_HINT = "decision_followup"


async def fetch_yesterday_prologue(
    *,
    atlas_ask: Callable[[str, str], Awaitable[dict]],
) -> Optional[str]:
    """Ask Atlas to synthesize the "what acted on yesterday" prologue.

    Returns the first-sentence summary string, or ``None`` if Atlas
    returns empty / errors. The /daily plugin renders this as a
    context block at the top of today's brief when present.

    This is the *read-back* half of the write-back loop: yesterday's
    AgentDecision triple (written by 026-B's sync write) + today's
    reaction states (filled in by the 12h harvest) + today's
    Linear/Pipedrive state diffs (synthesized server-side from the
    typed graph) feed Atlas's answer to ``YESTERDAY_PROLOGUE_QUESTION``.

    Failure semantics: any exception or empty answer returns ``None``;
    the brief renders without a prologue and the reader doesn't know
    the synthesis was attempted. This is intentional: a "no prologue"
    brief is a normal first-week state while the corpus warms up.
    """
    try:
        payload = await atlas_ask(YESTERDAY_PROLOGUE_QUESTION, YESTERDAY_PROLOGUE_HINT)
    except Exception as exc:
        logger.info("[daily.prologue] atlas_ask failed: %s", exc)
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("error"):
        return None
    answer = (payload.get("answer") or "").strip()
    if not answer:
        return None
    # First-sentence trim mirrors _summarize_atlas_response so the
    # prologue is one bullet-sized line, not a wall of text.
    first = answer.split("\n", 1)[0].strip()
    if len(first) > 240:
        first = first[:237] + "..."
    return first


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _written_urns_for_tests() -> tuple[str, ...]:
    """Read the in-process idempotency cache from tests."""
    return tuple(_WRITTEN_URNS)
