"""Tests for ``hermes slack-inject`` CLI subcommand — Plan 005-C.

Three test cases as specified:
  1. CLI argument parsing — defaults populate from env; explicit flags override.
  2. Synthetic event has correct shape (all required Socket Mode message fields).
  3. Calls ``_handle_slack_message`` (mocked) exactly once with the constructed event.

Implementation notes:
- No real Bolt / Slack SDK I/O. SlackAdapter is instantiated but _app is mocked.
- GatewayRunner is also mocked out so tests run offline without a live config.
- Uses pytest's monkeypatch for env vars and AsyncMock for the handler.
"""
from __future__ import annotations

import asyncio
import sys
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Ensure slack-bolt mocks are installed so SlackAdapter can be imported
# ---------------------------------------------------------------------------

def _ensure_slack_mock() -> None:
    """Install minimal slack-bolt stubs if the real library is not present."""
    if "slack_bolt" in sys.modules and hasattr(sys.modules["slack_bolt"], "__file__"):
        return

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


_ensure_slack_mock()


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

from hermes_cli.slack_inject import (  # noqa: E402
    build_synthetic_slack_event,
    _get_default_user_id,
    _get_default_channel_id,
    slack_inject_command,
    _run_inject,
)


# ---------------------------------------------------------------------------
# Test Case 1: CLI argument parsing
# ---------------------------------------------------------------------------

class TestSlackInjectArgParsing:
    """Case 1 — defaults populate from env; explicit flags override."""

    def test_defaults_from_env_user_id(self, monkeypatch):
        """SLACK_ALLOWED_USERS first entry becomes default user_id."""
        monkeypatch.setenv("SLACK_ALLOWED_USERS", "U_ENV_USER,U_SECOND")
        monkeypatch.delenv("SLACK_DM_CHANNEL", raising=False)

        user_id = _get_default_user_id()
        assert user_id == "U_ENV_USER", (
            f"Expected 'U_ENV_USER' from SLACK_ALLOWED_USERS, got {user_id!r}"
        )

    def test_defaults_from_env_channel_id(self, monkeypatch, capsys):
        """SLACK_DM_CHANNEL becomes default channel_id."""
        monkeypatch.setenv("SLACK_DM_CHANNEL", "D_ENV_CHANNEL")

        channel_id = _get_default_channel_id()
        assert channel_id == "D_ENV_CHANNEL", (
            f"Expected 'D_ENV_CHANNEL' from SLACK_DM_CHANNEL, got {channel_id!r}"
        )

    def test_fallback_user_id_when_env_absent(self, monkeypatch):
        """When SLACK_ALLOWED_USERS is not set, fall back to 'U_INJECT_TEST'."""
        monkeypatch.delenv("SLACK_ALLOWED_USERS", raising=False)

        user_id = _get_default_user_id()
        assert user_id == "U_INJECT_TEST", (
            f"Expected fallback 'U_INJECT_TEST', got {user_id!r}"
        )

    def test_fallback_user_id_when_allowed_is_wildcard(self, monkeypatch):
        """When SLACK_ALLOWED_USERS='*', fall back to 'U_INJECT_TEST' (not the wildcard)."""
        monkeypatch.setenv("SLACK_ALLOWED_USERS", "*")

        user_id = _get_default_user_id()
        assert user_id == "U_INJECT_TEST", (
            f"Wildcard '*' should not be used as user_id, got {user_id!r}"
        )

    def test_fallback_channel_id_when_env_absent(self, monkeypatch, capsys):
        """When SLACK_DM_CHANNEL is not set, fall back to 'D_TEST_CHANNEL'."""
        monkeypatch.delenv("SLACK_DM_CHANNEL", raising=False)

        channel_id = _get_default_channel_id()
        assert channel_id == "D_TEST_CHANNEL", (
            f"Expected fallback 'D_TEST_CHANNEL', got {channel_id!r}"
        )
        # Should also warn to stderr
        captured = capsys.readouterr()
        assert "WARNING" in captured.err, "Expected a WARNING message when SLACK_DM_CHANNEL is absent"

    def test_explicit_args_override_env(self, monkeypatch):
        """Explicit --user-id and --channel-id override env defaults."""
        monkeypatch.setenv("SLACK_ALLOWED_USERS", "U_ENV_DEFAULT")
        monkeypatch.setenv("SLACK_DM_CHANNEL", "D_ENV_DEFAULT")

        # Simulate argparse Namespace with explicit values
        args = SimpleNamespace(
            text="hello world",
            user_id="U_EXPLICIT",
            channel_id="D_EXPLICIT",
            thread_ts=None,
        )

        # Capture call to _run_inject (mocked)
        captured: dict = {}

        async def _fake_run_inject(text, user_id, channel_id, thread_ts):
            captured["user_id"] = user_id
            captured["channel_id"] = channel_id
            captured["text"] = text

        with patch("hermes_cli.slack_inject._run_inject", new=_fake_run_inject):
            slack_inject_command(args)

        assert captured["user_id"] == "U_EXPLICIT", (
            f"Expected 'U_EXPLICIT', got {captured['user_id']!r}"
        )
        assert captured["channel_id"] == "D_EXPLICIT", (
            f"Expected 'D_EXPLICIT', got {captured['channel_id']!r}"
        )


# ---------------------------------------------------------------------------
# Test Case 2: Synthetic event shape
# ---------------------------------------------------------------------------

class TestSyntheticEventShape:
    """Case 2 — all required Socket Mode message-event fields are present."""

    REQUIRED_FIELDS = {"type", "user", "channel", "text", "ts"}

    def test_all_required_fields_present(self):
        """build_synthetic_slack_event must include all required Socket Mode fields."""
        event = build_synthetic_slack_event(
            text="test ping",
            user_id="U_TEST",
            channel_id="D_TEST",
        )
        missing = self.REQUIRED_FIELDS - event.keys()
        assert not missing, f"Missing required event fields: {missing}"

    def test_type_is_message(self):
        """Event type must be 'message'."""
        event = build_synthetic_slack_event(
            text="hello",
            user_id="U_TEST",
            channel_id="D_TEST",
        )
        assert event["type"] == "message", (
            f"Expected type='message', got {event['type']!r}"
        )

    def test_user_and_channel_match_inputs(self):
        """user and channel fields must match the inputs."""
        event = build_synthetic_slack_event(
            text="some text",
            user_id="U_ALICE",
            channel_id="D_BOB",
        )
        assert event["user"] == "U_ALICE"
        assert event["channel"] == "D_BOB"

    def test_text_matches_input(self):
        """text field must be exactly the supplied text."""
        event = build_synthetic_slack_event(
            text="plan: research 1 firm",
            user_id="U_TEST",
            channel_id="D_TEST",
        )
        assert event["text"] == "plan: research 1 firm"

    def test_ts_is_string_float(self):
        """ts must be a string representation of a float (Unix timestamp)."""
        import re
        event = build_synthetic_slack_event(
            text="ts check",
            user_id="U_TEST",
            channel_id="D_TEST",
        )
        ts = event["ts"]
        assert isinstance(ts, str), f"ts should be a str, got {type(ts).__name__}"
        # Should look like "1716000000.123456" — digits, dot, up to 6 decimal places
        assert re.match(r"^\d+\.\d+$", ts), f"ts format unexpected: {ts!r}"

    def test_channel_type_is_im(self):
        """channel_type should be 'im' to force the DM code path."""
        event = build_synthetic_slack_event(
            text="dm test",
            user_id="U_TEST",
            channel_id="D_TEST",
        )
        assert event.get("channel_type") == "im", (
            f"Expected channel_type='im', got {event.get('channel_type')!r}"
        )

    def test_team_defaults_to_env_or_test(self, monkeypatch):
        """team field should use SLACK_TEAM_ID env var or fall back to 'T_TEST'."""
        monkeypatch.setenv("SLACK_TEAM_ID", "T_ENV_TEAM")
        event = build_synthetic_slack_event(
            text="team check",
            user_id="U_TEST",
            channel_id="D_TEST",
        )
        assert event["team"] == "T_ENV_TEAM"

    def test_team_fallback_without_env(self, monkeypatch):
        """When SLACK_TEAM_ID is absent, team defaults to 'T_TEST'."""
        monkeypatch.delenv("SLACK_TEAM_ID", raising=False)
        event = build_synthetic_slack_event(
            text="team fallback",
            user_id="U_TEST",
            channel_id="D_TEST",
        )
        assert event["team"] == "T_TEST"

    def test_thread_ts_none_when_not_supplied(self):
        """thread_ts must be None when not explicitly supplied."""
        event = build_synthetic_slack_event(
            text="no thread",
            user_id="U_TEST",
            channel_id="D_TEST",
        )
        assert event["thread_ts"] is None

    def test_thread_ts_set_when_supplied(self):
        """thread_ts must be echoed through when supplied."""
        event = build_synthetic_slack_event(
            text="in thread",
            user_id="U_TEST",
            channel_id="D_TEST",
            thread_ts="1716000000.111111",
        )
        assert event["thread_ts"] == "1716000000.111111"


# ---------------------------------------------------------------------------
# Test Case 3: _handle_slack_message called exactly once with the event
# ---------------------------------------------------------------------------

class TestHandlerInvocation:
    """Case 3 — ``_handle_slack_message`` (mocked) is called once with the event."""

    @pytest.mark.asyncio
    async def test_handle_slack_message_called_once(self, monkeypatch):
        """_run_inject must call adapter._handle_slack_message exactly once."""
        import gateway.platforms.slack as _slack_mod

        _slack_mod.SLACK_AVAILABLE = True

        # Build a fresh minimal adapter manually (same as _build_minimal_slack_adapter)
        from gateway.config import Platform, PlatformConfig
        from gateway.platforms.slack import SlackAdapter

        slack_cfg = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(slack_cfg)

        # Wire a mock _app so `if not self._app` guards pass
        mock_app = MagicMock()
        mock_app.client = AsyncMock()
        adapter._app = mock_app
        adapter._bot_user_id = "U_BOT_TEST"

        # Replace _handle_slack_message with an AsyncMock to capture the call
        handle_mock = AsyncMock(return_value=None)
        adapter._handle_slack_message = handle_mock

        # Mock _build_minimal_slack_adapter and _build_gateway_runner_for_inject
        # so _run_inject uses our controlled adapter.
        mock_runner = MagicMock()
        mock_runner.adapters = {}
        mock_runner._handle_message = AsyncMock()

        monkeypatch.setattr(
            "hermes_cli.slack_inject._build_minimal_slack_adapter",
            lambda: adapter,
        )
        monkeypatch.setattr(
            "hermes_cli.slack_inject._build_gateway_runner_for_inject",
            lambda: mock_runner,
        )

        # Also mock set_message_handler so it doesn't fail on our mock runner
        adapter.set_message_handler = MagicMock()

        await _run_inject(
            text="plan: research 1 firm",
            user_id="U_TESTER",
            channel_id="D_TEST_CH",
            thread_ts=None,
        )

        # Assert _handle_slack_message was called exactly once
        handle_mock.assert_called_once()

        # Assert the call arg is the correct event dict
        call_args = handle_mock.call_args
        assert call_args is not None, "_handle_slack_message was never called"
        event_arg = call_args.args[0]
        assert isinstance(event_arg, dict), (
            f"Expected a dict event arg, got {type(event_arg).__name__}"
        )
        assert event_arg["text"] == "plan: research 1 firm"
        assert event_arg["user"] == "U_TESTER"
        assert event_arg["channel"] == "D_TEST_CH"
        assert event_arg["type"] == "message"

    @pytest.mark.asyncio
    async def test_handle_slack_message_receives_all_required_fields(self, monkeypatch):
        """Event passed to _handle_slack_message must contain all required fields."""
        import gateway.platforms.slack as _slack_mod

        _slack_mod.SLACK_AVAILABLE = True

        from gateway.config import PlatformConfig
        from gateway.platforms.slack import SlackAdapter

        slack_cfg = PlatformConfig(enabled=True, token="xoxb-fake")
        adapter = SlackAdapter(slack_cfg)
        mock_app = MagicMock()
        mock_app.client = AsyncMock()
        adapter._app = mock_app
        adapter._bot_user_id = "U_BOT_TEST"

        received_events: list = []

        async def _capture_event(event):
            received_events.append(event)

        adapter._handle_slack_message = _capture_event

        mock_runner = MagicMock()
        mock_runner.adapters = {}
        mock_runner._handle_message = AsyncMock()
        adapter.set_message_handler = MagicMock()

        monkeypatch.setattr(
            "hermes_cli.slack_inject._build_minimal_slack_adapter",
            lambda: adapter,
        )
        monkeypatch.setattr(
            "hermes_cli.slack_inject._build_gateway_runner_for_inject",
            lambda: mock_runner,
        )

        await _run_inject(
            text="test ping",
            user_id="U_TESTER",
            channel_id="D_TEST_CH",
            thread_ts=None,
        )

        assert len(received_events) == 1, (
            f"Expected exactly 1 event captured, got {len(received_events)}"
        )
        event = received_events[0]
        for field in ("type", "user", "channel", "text", "ts"):
            assert field in event, f"Required field {field!r} missing from injected event"
