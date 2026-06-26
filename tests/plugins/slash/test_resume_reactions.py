"""Tests for Plan 029-F — reaction-driven `/resume` on drainTierGraph.

The reaction handler maps three emojis (🔄 / ⏭ / 🛑) on a
`phase_escalated` DM to existing Temporal signals on the drain
workflow. Routing logic lives entirely in
``plugins.slash.orchestrator.handle_reaction_event`` so it can be
exercised without the Slack gateway in scope.

ACs covered:

* Three reactions trigger the correct signals (retry / skip / halt).
* `[escalation]` marker is required — incidental reactions on other
  messages stay silent.
* Phase id is extracted from the message body; missing phase_id with a
  retry/skip reaction is a no-op.
* Unauthorised reactor is rejected silently when an allowlist is
  provided.
* Halt path uses the dedicated `halt_drain` signal (not manual_resume).
"""

from __future__ import annotations

from typing import Any

import pytest

from plugins.slash import orchestrator as slash_mod
from plugins.slash.orchestrator import (
    ALL_RESUME_REACTIONS,
    HALT_REACTIONS,
    HALT_DRAIN_SIGNAL,
    RETRY_REACTIONS,
    SKIP_REACTIONS,
    _classify_reaction,
    _extract_phase_id_from_text,
    handle_reaction_event,
    is_escalation_message_text,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


_ESCALATION_BODY = (
    "[escalation] phase=020-E failed after 2 retries. "
    "Signature: aaaa1111. React 🔄 to retry, ⏭ to skip, 🛑 to halt the drain."
)


@pytest.fixture(autouse=True)
def _enable_drain_control(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests exercise the drain-control-ENABLED behavior; turn the gate on.
    (Default-off behavior is covered by test_drain_control_gate.py.)"""
    monkeypatch.setenv("HERMES_DRAIN_CONTROL", "1")


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """Replace the sync signal entrypoints with recorders."""
    bucket: dict[str, list[Any]] = {"resume": [], "halt": []}

    def fake_resume(phase_id: str, action: str) -> None:
        bucket["resume"].append((phase_id, action))

    def fake_halt(reason: str) -> None:
        bucket["halt"].append(reason)

    monkeypatch.setattr(slash_mod, "_signal_sync", fake_resume)
    monkeypatch.setattr(slash_mod, "_signal_halt_sync", fake_halt)
    return bucket


# ---------------------------------------------------------------------------
# Classification + parsing units
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(RETRY_REACTIONS))
def test_classify_retry_aliases(name: str) -> None:
    assert _classify_reaction(name) == "retry"
    assert _classify_reaction(f":{name}:") == "retry"


@pytest.mark.parametrize("name", sorted(SKIP_REACTIONS))
def test_classify_skip_aliases(name: str) -> None:
    assert _classify_reaction(name) == "skip"


@pytest.mark.parametrize("name", sorted(HALT_REACTIONS))
def test_classify_halt_aliases(name: str) -> None:
    assert _classify_reaction(name) == "halt"


def test_classify_unrelated_emoji_returns_none() -> None:
    assert _classify_reaction("eyes") is None
    assert _classify_reaction("pushpin") is None
    assert _classify_reaction("") is None


def test_all_resume_reactions_is_union() -> None:
    assert ALL_RESUME_REACTIONS == (
        RETRY_REACTIONS | SKIP_REACTIONS | HALT_REACTIONS
    )


def test_extract_phase_id_picks_inline_phase_kv() -> None:
    assert _extract_phase_id_from_text(_ESCALATION_BODY) == "020-E"


def test_extract_phase_id_handles_dashed_prefix() -> None:
    body = "[escalation] phase=hub-020-E failed."
    assert _extract_phase_id_from_text(body) == "hub-020-E"


def test_extract_phase_id_fallback_token_scan() -> None:
    body = "[escalation] something went wrong with atlas-019-B over here."
    assert _extract_phase_id_from_text(body) == "atlas-019-B"


def test_extract_phase_id_returns_none_when_absent() -> None:
    assert _extract_phase_id_from_text("[escalation] nothing parseable") is None


def test_is_escalation_message_marker() -> None:
    assert is_escalation_message_text(_ESCALATION_BODY) is True
    assert is_escalation_message_text("just a regular message") is False
    assert is_escalation_message_text("") is False


# ---------------------------------------------------------------------------
# AC1 — three reactions, three signals
# ---------------------------------------------------------------------------


def test_retry_reaction_fires_manual_resume_retry(captured) -> None:
    note = handle_reaction_event(
        emoji_name="arrows_counterclockwise",
        message_text=_ESCALATION_BODY,
    )
    assert captured["resume"] == [("020-E", "retry")]
    assert captured["halt"] == []
    assert note is not None and "020-E" in note


def test_skip_reaction_fires_manual_resume_skip(captured) -> None:
    note = handle_reaction_event(
        emoji_name="next_track",
        message_text=_ESCALATION_BODY,
    )
    assert captured["resume"] == [("020-E", "skip")]
    assert captured["halt"] == []
    assert note is not None and "020-E" in note


def test_halt_reaction_fires_halt_drain_signal(captured) -> None:
    note = handle_reaction_event(
        emoji_name="octagonal_sign",
        message_text=_ESCALATION_BODY,
    )
    # halt_drain uses its own signal, not manual_resume.
    assert captured["resume"] == []
    assert captured["halt"] == ["slack-reaction:octagonal_sign"]
    assert note is not None and "halt_drain" in note


# ---------------------------------------------------------------------------
# AC2 — escalation marker is required
# ---------------------------------------------------------------------------


def test_reaction_on_non_escalation_message_is_silent(captured) -> None:
    note = handle_reaction_event(
        emoji_name="arrows_counterclockwise",
        message_text="hey, want to grab coffee? 020-E",
    )
    assert captured == {"resume": [], "halt": []}
    assert note is None


def test_halt_reaction_on_non_escalation_message_is_silent(captured) -> None:
    note = handle_reaction_event(
        emoji_name="octagonal_sign",
        message_text="random thread",
    )
    assert captured == {"resume": [], "halt": []}
    assert note is None


# ---------------------------------------------------------------------------
# AC3 — missing phase_id with retry/skip is a no-op (halt doesn't need one)
# ---------------------------------------------------------------------------


def test_retry_without_phase_id_is_noop(captured) -> None:
    note = handle_reaction_event(
        emoji_name="repeat",
        message_text="[escalation] something went sideways, no phase here",
    )
    assert captured == {"resume": [], "halt": []}
    assert note is None


def test_halt_without_phase_id_still_fires(captured) -> None:
    """Halt is whole-drain, so it doesn't need a phase_id to dispatch."""
    note = handle_reaction_event(
        emoji_name="stop_sign",
        message_text="[escalation] no specific phase mentioned",
    )
    assert captured["halt"] == ["slack-reaction:stop_sign"]
    assert note is not None


# ---------------------------------------------------------------------------
# AC4 — unauthorised reactor rejected silently
# ---------------------------------------------------------------------------


def test_unauthorised_reactor_is_dropped_silently(captured) -> None:
    note = handle_reaction_event(
        emoji_name="arrows_counterclockwise",
        message_text=_ESCALATION_BODY,
        reactor_user_id="U_RANDO",
        allowed_users={"U_BLAKE"},
    )
    assert captured == {"resume": [], "halt": []}
    assert note is None


def test_authorised_reactor_passes_through(captured) -> None:
    note = handle_reaction_event(
        emoji_name="arrows_counterclockwise",
        message_text=_ESCALATION_BODY,
        reactor_user_id="U_BLAKE",
        allowed_users={"U_BLAKE"},
    )
    assert captured["resume"] == [("020-E", "retry")]
    assert note is not None


def test_no_allowlist_means_no_auth_check(captured) -> None:
    """``allowed_users=None`` lets the gateway's pre-check decide."""
    note = handle_reaction_event(
        emoji_name="octagonal_sign",
        message_text=_ESCALATION_BODY,
        reactor_user_id="U_ANYONE",
        allowed_users=None,
    )
    assert captured["halt"] == ["slack-reaction:octagonal_sign"]
    assert note is not None


# ---------------------------------------------------------------------------
# AC5 — Temporal signal errors return a Slack-friendly note rather than raise
# ---------------------------------------------------------------------------


def test_signal_error_returns_friendly_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom_resume(phase_id: str, action: str) -> None:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(slash_mod, "_signal_sync", boom_resume)

    note = handle_reaction_event(
        emoji_name="arrows_counterclockwise",
        message_text=_ESCALATION_BODY,
    )
    assert note is not None
    assert ":x:" in note
    assert "020-E" in note
    assert "connection refused" in note


def test_halt_signal_error_returns_friendly_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom_halt(reason: str) -> None:
        raise RuntimeError("temporal frontend unreachable")

    monkeypatch.setattr(slash_mod, "_signal_halt_sync", boom_halt)

    note = handle_reaction_event(
        emoji_name="octagonal_sign",
        message_text=_ESCALATION_BODY,
    )
    assert note is not None
    assert ":x:" in note
    assert "halt_drain" in note


# ---------------------------------------------------------------------------
# Signal constant + symbol exports
# ---------------------------------------------------------------------------


def test_halt_signal_name_is_stable() -> None:
    """The signal name is part of the cross-repo contract with drainTierGraph.

    Any rename here MUST be paired with a rename in
    ``agentic-hub/orchestrator/workflows/drain_tier_graph.py:HALT_DRAIN_SIGNAL``.
    """
    assert HALT_DRAIN_SIGNAL == "halt_drain"
