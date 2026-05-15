"""Tests for Plan 005-B: Rooben prefix-based routing in _handle_message.

Verifies that messages starting with "plan:" or "/workflow " are dispatched
to _dispatch_to_rooben, and all other messages fall through to the normal
run_conversation path.

Test cases:
  1. "plan: research 3 PE firms"     → triggers _dispatch_to_rooben
  2. "/workflow do something"        → triggers _dispatch_to_rooben
  3. "what's 2+2?"                   → does NOT trigger (free-form path)
  4. Case-insensitive: "Plan: ...",
     "PLAN: ..."                     → both trigger
  5. Whitespace tolerance: "  plan:  research..."  → triggers
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(text: str, platform: Platform = Platform.WHATSAPP) -> MessageEvent:
    return MessageEvent(
        text=text,
        message_id="m1",
        source=SessionSource(
            platform=platform,
            user_id="15551234567@s.whatsapp.net",
            chat_id="15551234567@s.whatsapp.net",
            user_name="tester",
            chat_type="dm",
        ),
    )


def _make_runner(platform: Platform = Platform.WHATSAPP):
    """Build a minimal GatewayRunner without real adapters or DB.

    Follows the same pattern as test_pre_gateway_dispatch.py — uses
    object.__new__ to skip __init__ and wire only what _handle_message needs.
    """
    from gateway.run import GatewayRunner

    config = GatewayConfig(
        platforms={platform: PlatformConfig(enabled=True)},
    )
    runner = object.__new__(GatewayRunner)
    runner.config = config
    adapter = SimpleNamespace(
        send=AsyncMock(),
        _send_with_retry=AsyncMock(),
    )
    runner.adapters = {platform: adapter}
    runner.pairing_store = MagicMock()
    runner.pairing_store.is_approved.return_value = True
    runner.pairing_store._is_rate_limited.return_value = False
    runner.session_store = MagicMock()
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._update_prompt_pending = {}
    return runner, adapter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_plan_prefix_triggers_dispatch(monkeypatch):
    """'plan: <request>' should call _dispatch_to_rooben, not the normal path."""
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "*")
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *a, **kw: [])

    runner, _adapter = _make_runner()
    dispatch_called: dict = {}

    async def _mock_dispatch(event, nl_request):
        dispatch_called["nl_request"] = nl_request
        return None

    runner._dispatch_to_rooben = _mock_dispatch

    await runner._handle_message(_make_event("plan: research 3 PE firms"))

    assert dispatch_called.get("nl_request") == "research 3 PE firms", (
        f"Expected nl_request='research 3 PE firms', got {dispatch_called!r}"
    )


@pytest.mark.asyncio
async def test_workflow_prefix_triggers_dispatch(monkeypatch):
    """'/workflow <request>' should call _dispatch_to_rooben."""
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "*")
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *a, **kw: [])

    runner, _adapter = _make_runner()
    dispatch_called: dict = {}

    async def _mock_dispatch(event, nl_request):
        dispatch_called["nl_request"] = nl_request
        return None

    runner._dispatch_to_rooben = _mock_dispatch

    await runner._handle_message(_make_event("/workflow do something"))

    assert dispatch_called.get("nl_request") == "do something", (
        f"Expected nl_request='do something', got {dispatch_called!r}"
    )


@pytest.mark.asyncio
async def test_free_form_does_not_trigger_dispatch(monkeypatch):
    """A plain message (no prefix) must NOT call _dispatch_to_rooben."""
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "*")
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *a, **kw: [])

    runner, _adapter = _make_runner()
    dispatch_called: dict = {"called": False}

    async def _mock_dispatch(event, nl_request):
        dispatch_called["called"] = True
        return None

    async def _mock_agent_handler(event, source, _quick_key, _run_generation):
        return "free-form response"

    runner._dispatch_to_rooben = _mock_dispatch
    runner._handle_message_with_agent = _mock_agent_handler

    await runner._handle_message(_make_event("what's 2+2?"))

    assert not dispatch_called["called"], (
        "_dispatch_to_rooben should NOT be called for a non-prefixed message"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "Plan: research 3 PE firms",
    "PLAN: research 3 PE firms",
    "pLaN: research 3 PE firms",
])
async def test_plan_prefix_case_insensitive(text, monkeypatch):
    """plan: prefix must match regardless of case."""
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "*")
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *a, **kw: [])

    runner, _adapter = _make_runner()
    dispatch_called: dict = {}

    async def _mock_dispatch(event, nl_request):
        dispatch_called["nl_request"] = nl_request
        return None

    runner._dispatch_to_rooben = _mock_dispatch

    await runner._handle_message(_make_event(text))

    assert "nl_request" in dispatch_called, (
        f"_dispatch_to_rooben was not called for text={text!r}"
    )
    # NL request should have the prefix stripped and be trimmed
    assert dispatch_called["nl_request"] == "research 3 PE firms", (
        f"nl_request mismatch for text={text!r}: got {dispatch_called['nl_request']!r}"
    )


@pytest.mark.asyncio
async def test_plan_prefix_whitespace_tolerance(monkeypatch):
    """Leading whitespace before 'plan:' should be stripped and still trigger routing."""
    monkeypatch.setenv("WHATSAPP_ALLOWED_USERS", "*")
    monkeypatch.setattr("hermes_cli.plugins.invoke_hook", lambda *a, **kw: [])

    runner, _adapter = _make_runner()
    dispatch_called: dict = {}

    async def _mock_dispatch(event, nl_request):
        dispatch_called["nl_request"] = nl_request
        return None

    runner._dispatch_to_rooben = _mock_dispatch

    # Leading spaces before "plan:" and extra spaces after the colon
    await runner._handle_message(_make_event("  plan:  research mid-market PE firms"))

    assert "nl_request" in dispatch_called, (
        "_dispatch_to_rooben was not called for whitespace-padded 'plan:' input"
    )
    assert dispatch_called["nl_request"] == "research mid-market PE firms", (
        f"nl_request should be trimmed, got {dispatch_called['nl_request']!r}"
    )
