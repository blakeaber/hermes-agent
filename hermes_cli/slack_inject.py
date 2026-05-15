"""``hermes slack-inject "<text>"`` CLI subcommand — Plan 005-C.

Simulates a real-user Slack DM without going through the actual Slack Socket
Mode connection. Builds a synthetic event dict matching what Socket Mode
delivers for a ``message.im`` event, then calls the Slack adapter's
``_handle_slack_message()`` directly.

This exercises everything from the Slack message handler downward — including
Phase 005-B's prefix-routing classifier (``plan:`` / ``/workflow `` triggers).

Usage::

    hermes slack-inject "test ping"
    hermes slack-inject "plan: research 1 PE firm" --user-id U123 --channel-id D456

Environment variables used for defaults (all optional):
    SLACK_ALLOWED_USERS   — comma-separated user IDs allowed by the gateway.
                            First entry is used as the injected user_id.
                            Falls back to ``U_INJECT_TEST``.
    SLACK_DM_CHANNEL      — default channel ID for DM events.
                            Falls back to ``D_TEST_CHANNEL`` with a warning.
    SLACK_TEAM_ID         — team/workspace ID embedded in the event.
                            Falls back to ``T_TEST``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Event builder
# ---------------------------------------------------------------------------


def build_synthetic_slack_event(
    text: str,
    user_id: str,
    channel_id: str,
    thread_ts: Optional[str] = None,
) -> dict:
    """Return a minimal Socket Mode ``message.im`` event dict.

    The shape matches what Slack's Socket Mode API delivers for an inbound DM.
    Fields are chosen to give ``_handle_slack_message`` everything it reads:
    ``type``, ``user``, ``channel``, ``text``, ``ts``, ``thread_ts``, ``team``,
    and ``channel_type`` (set to ``"im"`` so the DM path fires without relying
    on the ``D``-prefix heuristic only).
    """
    ts = f"{time.time():.6f}"
    team_id = os.environ.get("SLACK_TEAM_ID", "T_TEST")

    event: dict = {
        "type": "message",
        "user": user_id,
        "channel": channel_id,
        "channel_type": "im",  # force DM path; channel starts with D already
        "text": text,
        "ts": ts,
        "thread_ts": thread_ts or None,
        "team": team_id,
    }
    return event


# ---------------------------------------------------------------------------
# Adapter bootstrap (minimal, no Bolt socket connection)
# ---------------------------------------------------------------------------


def _get_default_user_id() -> str:
    """Return the first user ID from SLACK_ALLOWED_USERS, else a test placeholder."""
    allowed = os.environ.get("SLACK_ALLOWED_USERS", "").strip()
    if allowed:
        first = next(
            (uid.strip() for uid in allowed.split(",") if uid.strip()), None
        )
        if first and first != "*":
            return first
    return "U_INJECT_TEST"


def _get_default_channel_id() -> str:
    """Return SLACK_DM_CHANNEL env var, else a fallback placeholder with a warning."""
    channel = os.environ.get("SLACK_DM_CHANNEL", "").strip()
    if channel:
        return channel
    print(
        "[slack-inject] WARNING: SLACK_DM_CHANNEL is not set. "
        "Using placeholder 'D_TEST_CHANNEL'. "
        "Real Slack API calls from the handler (e.g. users.info) will fail, "
        "but the routing/test path still works.",
        file=sys.stderr,
    )
    return "D_TEST_CHANNEL"


def _build_minimal_slack_adapter():
    """Instantiate a SlackAdapter without starting the Bolt Socket Mode connection.

    The adapter is built from the gateway config so it inherits the same
    platform config that a live gateway would use. ``_app`` is set to a
    MagicMock so the many ``if not self._app: return`` guards in the adapter
    code pass, but without attempting any real Bolt or WebSocket I/O.

    Returns the adapter instance.
    """
    from unittest.mock import AsyncMock, MagicMock

    # Ensure slack-bolt mock is in place if the real library isn't installed
    _ensure_slack_mock()

    import gateway.platforms.slack as _slack_mod

    _slack_mod.SLACK_AVAILABLE = True

    from gateway.config import Platform, PlatformConfig, load_gateway_config
    from gateway.platforms.slack import SlackAdapter

    cfg = load_gateway_config()

    # Use the Slack platform config from disk; fall back to a minimal one.
    slack_cfg = cfg.platforms.get(Platform.SLACK)
    if slack_cfg is None or not slack_cfg.enabled:
        slack_cfg = PlatformConfig(enabled=True, token=os.environ.get("SLACK_BOT_TOKEN", "xoxb-inject-test"))

    adapter = SlackAdapter(slack_cfg)

    # Wire a mock Bolt app so ``if not self._app`` guards pass.
    # API calls like users_info() will be no-ops (AsyncMock returns MagicMock).
    mock_client = AsyncMock()
    mock_client.users_info = AsyncMock(return_value={"ok": True, "user": {"profile": {}}})
    mock_client.reactions_add = AsyncMock(return_value={"ok": True})
    mock_client.chat_postMessage = AsyncMock(return_value={"ok": True, "ts": "0.0"})

    mock_app = MagicMock()
    mock_app.client = mock_client

    adapter._app = mock_app
    adapter._bot_user_id = os.environ.get("SLACK_BOT_USER_ID", "U_BOT_INJECT")
    adapter._running = True

    return adapter


def _build_gateway_runner_for_inject():
    """Build a GatewayRunner from the live config for message routing.

    The runner is constructed normally (so it loads config, session store, etc.)
    but is NOT started (no event loop, no socket connections). This gives us
    access to ``_handle_message`` — including the Plan 005-B prefix router —
    without standing up the full gateway.
    """
    from gateway.run import GatewayRunner

    runner = GatewayRunner()
    return runner


def _ensure_slack_mock() -> None:
    """Install minimal slack-bolt mocks if the library is not installed.

    Mirrors the pattern in ``tests/gateway/test_slack.py`` so the import of
    SlackAdapter succeeds even in environments without slack-bolt installed.
    """
    if "slack_bolt" in sys.modules and hasattr(sys.modules["slack_bolt"], "__file__"):
        return  # Real library installed — nothing to do

    from unittest.mock import MagicMock

    slack_bolt = MagicMock()
    slack_bolt.async_app.AsyncApp = MagicMock
    slack_bolt.adapter.socket_mode.async_handler.AsyncSocketModeHandler = MagicMock

    slack_sdk = MagicMock()
    slack_sdk.web.async_client.AsyncWebClient = MagicMock

    mods = [
        ("slack_bolt", slack_bolt),
        ("slack_bolt.async_app", slack_bolt.async_app),
        ("slack_bolt.adapter", slack_bolt.adapter),
        ("slack_bolt.adapter.socket_mode", slack_bolt.adapter.socket_mode),
        ("slack_bolt.adapter.socket_mode.async_handler", slack_bolt.adapter.socket_mode.async_handler),
        ("slack_sdk", slack_sdk),
        ("slack_sdk.web", slack_sdk.web),
        ("slack_sdk.web.async_client", slack_sdk.web.async_client),
    ]
    for name, mod in mods:
        sys.modules.setdefault(name, mod)

    sys.modules.setdefault("aiohttp", MagicMock())


# ---------------------------------------------------------------------------
# Async core
# ---------------------------------------------------------------------------


async def _run_inject(
    text: str,
    user_id: str,
    channel_id: str,
    thread_ts: Optional[str],
) -> None:
    """Build event, wire adapter to runner, call _handle_slack_message, print result."""
    event = build_synthetic_slack_event(
        text=text,
        user_id=user_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    print(
        f"[slack-inject] Building synthetic message.im event: "
        f"user={user_id} channel={channel_id} ts={event['ts']!r} text={text!r}",
        file=sys.stderr,
    )

    # Build the gateway runner (from live config, unstarted).
    print("[slack-inject] Initialising GatewayRunner from config …", file=sys.stderr)
    try:
        runner = _build_gateway_runner_for_inject()
    except Exception as exc:
        print(
            f"[slack-inject] ERROR: Could not build GatewayRunner: {exc}\n"
            "Make sure HERMES_HOME is set and gateway config exists.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Build a minimal SlackAdapter (no Bolt connection).
    print("[slack-inject] Building minimal SlackAdapter (no Socket Mode) …", file=sys.stderr)
    try:
        adapter = _build_minimal_slack_adapter()
    except Exception as exc:
        print(
            f"[slack-inject] ERROR: Could not build SlackAdapter: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    # Register the adapter with the runner (for _is_user_authorized and routing).
    from gateway.config import Platform
    runner.adapters[Platform.SLACK] = adapter

    # Wire the runner's message handler into the adapter.
    adapter.set_message_handler(runner._handle_message)

    # Invoke the Slack adapter's message handler directly — same call path
    # as Socket Mode would take after receiving the event from Slack.
    print("[slack-inject] Calling adapter._handle_slack_message(event) …", file=sys.stderr)
    result = None
    try:
        result = await adapter._handle_slack_message(event)
    except Exception as exc:
        print(
            f"[slack-inject] WARNING: _handle_slack_message raised {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )

    print(
        f"Injected event ts={event['ts']} user={user_id} text={text!r}. "
        f"Handler returned: {result!r}"
    )


# ---------------------------------------------------------------------------
# Public CLI entry point
# ---------------------------------------------------------------------------


def slack_inject_command(args) -> int:
    """Handle ``hermes slack-inject`` invocation.

    Parses args populated by argparse, builds the synthetic event, and runs
    the async inject pipeline synchronously via ``asyncio.run()``.
    """
    text: str = args.text
    thread_ts: Optional[str] = getattr(args, "thread_ts", None) or None

    # Resolve user_id
    user_id: str = getattr(args, "user_id", None) or ""
    if not user_id:
        user_id = _get_default_user_id()

    # Resolve channel_id
    channel_id: str = getattr(args, "channel_id", None) or ""
    if not channel_id:
        channel_id = _get_default_channel_id()

    try:
        asyncio.run(_run_inject(text=text, user_id=user_id, channel_id=channel_id, thread_ts=thread_ts))
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        print(f"[slack-inject] Fatal error: {exc}", file=sys.stderr)
        logger.exception("slack-inject fatal error")
        return 1

    return 0
