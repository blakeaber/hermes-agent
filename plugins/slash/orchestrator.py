"""/resume + /skip slash command handlers.

Both handlers parse a phase id from the raw slash-command arguments, connect
to the Temporal frontend, and signal the running ``drain-tier-graph`` parent
workflow with ``manual_resume`` + the appropriate action.

The handlers are synchronous (``fn(raw_args: str) -> str``) per
``PluginContext.register_command`` contract, but spin up an event loop to run
the async temporalio client call. We use ``asyncio.run`` so each invocation
gets a fresh loop — Hermes's gateway dispatches plugin commands in a
thread-pool, so no parent loop is in scope.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Phase ids look like ``<plan-id>-<letter>``:
#   ``020-A``, ``015-1C``, ``atlas-019-B``, ``hub-020-E``.
# The trailing token is one or more digits + a single A-Z letter.
PHASE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9]*[A-Z]$")

MANUAL_RESUME_SIGNAL = "manual_resume"
HALT_DRAIN_SIGNAL = "halt_drain"
DRAIN_WORKFLOW_ID = "drain-tier-graph"

# Plan 029-F — reaction-driven /resume. Three Slack reaction names map to
# the existing manual_resume + halt_drain signals on drainTierGraph. The
# Slack event payload's `reaction` field is the emoji's canonical name
# (no colons), so we match that exact set.
#
# We accept multiple aliases per intent because Slack's emoji aliasing
# (e.g. "track_next" vs "next_track") varies by workspace.
RETRY_REACTIONS: frozenset[str] = frozenset({
    "arrows_counterclockwise",
    "repeat",
})
SKIP_REACTIONS: frozenset[str] = frozenset({
    "next_track",
    "next_track_button",
    "track_next",
    "black_right_pointing_double_triangle_with_vertical_bar",
})
HALT_REACTIONS: frozenset[str] = frozenset({
    "octagonal_sign",
    "stop_sign",
    "no_entry",
})

# All three sets combined — cheap pre-filter for the Slack gateway so
# unrelated reactions aren't fan-out to this plugin.
ALL_RESUME_REACTIONS: frozenset[str] = (
    RETRY_REACTIONS | SKIP_REACTIONS | HALT_REACTIONS
)

# The escalation message marker. Hermes posts phase-escalation DMs with
# this prefix (matching the 020-E master plan's `[escalation]` tag); the
# reaction handler refuses to fire on any other message so incidental
# 🔄 / ⏭ / 🛑 reactions on unrelated content stay silent.
ESCALATION_TEXT_MARKER = "[escalation]"

# Regex matching a phase_id embedded anywhere in the message body. We
# only need to find the first match — the escalation message format
# is `[escalation] phase=<phase_id> ...`.
_PHASE_ID_INLINE_RE = re.compile(
    r"phase(?:[_-]?id)?\s*[=:]\s*([a-z0-9]+(?:-[a-z0-9]+)*-[0-9]*[A-Z])"
)

# Surface a constant Temporal Web URL so the operator can watch the retry.
# Defaults to the laptop bridge port shipped by 020-D; overridable for
# Fargate/Tailscale once 020-F lands.
_DEFAULT_TEMPORAL_WEB_URL = "http://localhost:8233"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_phase_id(raw_args: str) -> str | None:
    """Pull the first whitespace-delimited token and validate its shape.

    Returns the normalized phase id, or None if the input doesn't look like
    a valid phase id (we reject loudly to avoid signalling the workflow with
    garbage payloads).
    """
    if not raw_args:
        return None
    token = raw_args.strip().split()[0] if raw_args.strip() else ""
    if not token:
        return None
    if not PHASE_ID_PATTERN.match(token):
        return None
    return token


def _temporal_host() -> str:
    return os.environ.get("TEMPORAL_HOST", "localhost:7233")


def _temporal_namespace() -> str:
    return os.environ.get("TEMPORAL_NAMESPACE", "default")


def _temporal_web_url() -> str:
    return os.environ.get("TEMPORAL_WEB_URL", _DEFAULT_TEMPORAL_WEB_URL)


def _drain_control_enabled() -> bool:
    """Whether drain control (/resume, /skip, reaction signalling) is wired.

    OFF by default: this Hermes image ships without ``temporalio`` and prod sets
    no ``TEMPORAL_HOST``, so the signal path can't reach the drain workflow.
    Rather than present commands that fail with a misleading "TEMPORAL_HOST
    unreachable", we hide them (see ``plugins.slash.register``) and keep
    reactions silent until the capability is actually wired. Flip
    ``HERMES_DRAIN_CONTROL=1`` (and install temporalio + set TEMPORAL_HOST) to
    re-enable.
    """
    return os.environ.get("HERMES_DRAIN_CONTROL", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


async def _signal_drain_workflow(phase_id: str, action: str) -> None:
    """Open a Temporal client and signal the drain workflow.

    Imports ``temporalio`` lazily so the plugin can register on Hermes
    instances where temporalio isn't installed (it only becomes a hard
    requirement at signal time, and a clean error message is better than
    refusing to load the plugin).
    """
    try:
        from temporalio.client import Client  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "temporalio not installed in the Hermes environment — "
            "`pip install 'temporalio>=1.7,<2'` to enable /resume + /skip."
        ) from exc

    client = await Client.connect(_temporal_host(), namespace=_temporal_namespace())
    handle = client.get_workflow_handle(DRAIN_WORKFLOW_ID)
    payload: dict[str, Any] = {"phase_id": phase_id, "action": action}
    await handle.signal(MANUAL_RESUME_SIGNAL, payload)


async def _signal_halt_drain(reason: str) -> None:
    """Signal the drain workflow to halt all in-flight phases.

    Sends the dedicated ``halt_drain`` signal (handled by
    drainTierGraph in 029-F) which cancels in-flight executePhase
    children and returns DrainSummary(status="halted").
    """
    try:
        from temporalio.client import Client  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "temporalio not installed in the Hermes environment — "
            "`pip install 'temporalio>=1.7,<2'` to enable /resume + /skip."
        ) from exc

    client = await Client.connect(_temporal_host(), namespace=_temporal_namespace())
    handle = client.get_workflow_handle(DRAIN_WORKFLOW_ID)
    await handle.signal(HALT_DRAIN_SIGNAL, {"reason": reason})


def _signal_sync(phase_id: str, action: str) -> None:
    """Synchronous wrapper around ``_signal_drain_workflow``.

    Tests monkeypatch this function (rather than the async one) so they don't
    need an event loop to assert on call args.
    """
    asyncio.run(_signal_drain_workflow(phase_id, action))


def _signal_halt_sync(reason: str) -> None:
    """Synchronous wrapper around ``_signal_halt_drain``.

    Tests monkeypatch this function rather than the async one. Mirrors
    ``_signal_sync``'s contract so the reaction handler stays uniform.
    """
    asyncio.run(_signal_halt_drain(reason))


# ---------------------------------------------------------------------------
# Plan 029-F — Reaction event handlers
# ---------------------------------------------------------------------------


def _classify_reaction(emoji_name: str) -> str | None:
    """Map a Slack reaction name to one of {"retry", "skip", "halt"}.

    Returns None for any emoji outside our three-set. The Slack gateway
    pre-filters on ``ALL_RESUME_REACTIONS`` to avoid invoking this
    function for unrelated reactions in the first place; this is a
    belt-and-braces second pass that also strips colon-wrapping.
    """
    if not emoji_name:
        return None
    name = emoji_name.strip(": ")
    if name in RETRY_REACTIONS:
        return "retry"
    if name in SKIP_REACTIONS:
        return "skip"
    if name in HALT_REACTIONS:
        return "halt"
    return None


def _extract_phase_id_from_text(text: str) -> str | None:
    """Pull a phase_id out of an escalation message body.

    Escalation message format (from 020-D's ``_emit_escalation`` and
    the Hermes-side bridge): the body contains
    ``[escalation] phase=<phase_id>`` plus context. We look for the
    inline ``phase=`` token and fall back to any tail-token that matches
    the strict PHASE_ID_PATTERN.
    """
    if not text:
        return None
    m = _PHASE_ID_INLINE_RE.search(text)
    if m:
        return m.group(1)
    # Fallback: scan whitespace tokens for the strict pattern.
    for tok in text.split():
        cleaned = tok.strip(".,;:!?()[]{}'\"")
        if PHASE_ID_PATTERN.match(cleaned):
            return cleaned
    return None


def is_escalation_message_text(text: str) -> bool:
    """Return True iff ``text`` is a Hermes escalation DM.

    The Slack gateway uses this to drop reaction events on unrelated
    messages cheaply, before any signal fan-out.
    """
    if not text:
        return False
    return ESCALATION_TEXT_MARKER in text


def handle_reaction_event(
    *,
    emoji_name: str,
    message_text: str,
    reactor_user_id: str = "",
    allowed_users: set[str] | frozenset[str] | None = None,
) -> str | None:
    """Dispatch a reaction on an escalation message to the right signal.

    Parameters
    ----------
    emoji_name : str
        The canonical emoji name from the Slack ``reaction_added`` event
        (no colons). One of ``ALL_RESUME_REACTIONS`` for the call to do
        anything.
    message_text : str
        The body of the reacted-to message. Must contain
        ``[escalation]`` and a parseable phase_id.
    reactor_user_id : str
        Slack user id of the reactor; checked against ``allowed_users``
        when provided.
    allowed_users : set[str] | None
        Auth gate. ``None`` means "no allowlist enforced" (used by tests
        + by code paths where the gateway has already gated). The Slack
        gateway passes the parsed ``SLACK_ALLOWED_USERS`` set so an
        unauthorised reactor is dropped silently.

    Returns
    -------
    str | None
        A short human-readable note (used for logs / DM follow-up) when
        a signal was fired. ``None`` when the reaction was ignored
        (wrong emoji, not an escalation message, missing phase_id,
        unauthorised reactor, or Temporal unreachable).
    """
    # Honesty gate: when drain control isn't wired in this deployment, a 🔄/⏭/🛑
    # reaction can't signal anything — stay silent rather than firing a dead
    # Temporal call that returns a misleading ":x: signal failed" note.
    if not _drain_control_enabled():
        return None

    # Auth gate first — silent drop per AC4.
    if allowed_users is not None and reactor_user_id not in allowed_users:
        logger.debug(
            "reaction dropped: user %r not in SLACK_ALLOWED_USERS",
            reactor_user_id,
        )
        return None

    intent = _classify_reaction(emoji_name)
    if intent is None:
        return None

    if not is_escalation_message_text(message_text):
        logger.debug(
            "reaction %r ignored: message is not an [escalation] DM",
            emoji_name,
        )
        return None

    if intent == "halt":
        try:
            _signal_halt_sync(reason=f"slack-reaction:{emoji_name}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to signal halt_drain from reaction")
            return f":x: halt_drain signal failed: {exc}"
        return ":octagonal_sign: halt_drain signal sent. Cancelling in-flight phases."

    # retry / skip both need a phase_id.
    phase_id = _extract_phase_id_from_text(message_text)
    if phase_id is None:
        logger.warning(
            "reaction %r ignored: no phase_id parseable from message",
            emoji_name,
        )
        return None

    try:
        _signal_sync(phase_id, intent)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to signal %s for %s from reaction", intent, phase_id)
        return f":x: {intent} signal failed for {phase_id}: {exc}"

    if intent == "retry":
        return f":arrows_counterclockwise: retry signal sent for {phase_id}."
    return f":next_track: skip signal sent for {phase_id}."


# ---------------------------------------------------------------------------
# Slash command handlers
# ---------------------------------------------------------------------------


def _usage(cmd: str) -> str:
    return (
        f"Usage: /{cmd} <phase_id>\n"
        f"Example: /{cmd} 020-E\n"
        "Phase ids look like <plan-id>-<letter> "
        "(e.g. 020-E, 015-1C, atlas-019-B)."
    )


def handle_resume(raw_args: str) -> str:
    """``/resume <phase_id>`` — signal drainTierGraph to retry the phase."""
    phase_id = _parse_phase_id(raw_args)
    if phase_id is None:
        return _usage("resume")
    try:
        _signal_sync(phase_id, "retry")
    except Exception as exc:  # noqa: BLE001 — return a Slack-friendly error
        logger.exception("Failed to signal manual_resume retry for %s", phase_id)
        return (
            f":x: Failed to signal manual_resume for {phase_id}: {exc}. "
            "Check that the drain-tier-graph workflow is running and that "
            "TEMPORAL_HOST is reachable."
        )
    return (
        f":white_check_mark: Resume signal sent for {phase_id}. "
        f"Watch {_temporal_web_url()} for the new attempt."
    )


def handle_skip(raw_args: str) -> str:
    """``/skip <phase_id>`` — mark the phase permanently Blocked."""
    phase_id = _parse_phase_id(raw_args)
    if phase_id is None:
        return _usage("skip")
    try:
        _signal_sync(phase_id, "skip")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to signal manual_resume skip for %s", phase_id)
        return (
            f":x: Failed to signal skip for {phase_id}: {exc}. "
            "Check that the drain-tier-graph workflow is running."
        )
    return (
        f":white_check_mark: {phase_id} marked permanently Blocked. "
        "Downstream phases will stay Todo."
    )
