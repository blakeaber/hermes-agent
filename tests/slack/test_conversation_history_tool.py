"""
Tests for hermes_agent.slack.conversation_history_tool.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from hermes_agent.slack.conversation_history_tool import (
    ConversationHistoryError,
    ConversationHistoryInput,
    ConversationHistoryTool,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool(response: Dict[str, Any]) -> ConversationHistoryTool:
    """Return a ConversationHistoryTool backed by a mock Slack client."""
    client = MagicMock()
    client.conversations_history.return_value = response
    return ConversationHistoryTool(slack_client=client)


_SAMPLE_MESSAGES = [
    {"ts": "1700000001.000100", "user": "U111", "text": "Hello world"},
    {"ts": "1700000002.000200", "user": "U222", "text": "Hi there"},
]


# ---------------------------------------------------------------------------
# ConversationHistoryInput schema
# ---------------------------------------------------------------------------

class TestConversationHistoryInput:
    def test_valid_minimal(self):
        inp = ConversationHistoryInput(channel="C01234567")
        assert inp.channel == "C01234567"
        assert inp.limit == 20
        assert inp.oldest is None
        assert inp.latest is None

    def test_valid_full(self):
        inp = ConversationHistoryInput(
            channel="C01234567",
            limit=50,
            oldest="1700000000.000000",
            latest="1700001000.000000",
        )
        assert inp.limit == 50
        assert inp.oldest == "1700000000.000000"
        assert inp.latest == "1700001000.000000"

    def test_limit_lower_bound(self):
        inp = ConversationHistoryInput(channel="C0", limit=1)
        assert inp.limit == 1

    def test_limit_upper_bound(self):
        inp = ConversationHistoryInput(channel="C0", limit=200)
        assert inp.limit == 200

    def test_limit_below_minimum_raises(self):
        with pytest.raises(Exception):
            ConversationHistoryInput(channel="C0", limit=0)

    def test_limit_above_maximum_raises(self):
        with pytest.raises(Exception):
            ConversationHistoryInput(channel="C0", limit=201)


# ---------------------------------------------------------------------------
# ConversationHistoryTool.run
# ---------------------------------------------------------------------------

class TestConversationHistoryToolRun:
    def test_returns_messages_on_success(self):
        tool = _make_tool({"ok": True, "messages": _SAMPLE_MESSAGES})
        result = tool.run(channel="C01234567")
        assert result == _SAMPLE_MESSAGES

    def test_passes_channel_to_client(self):
        tool = _make_tool({"ok": True, "messages": []})
        tool.run(channel="C99999999")
        tool._client.conversations_history.assert_called_once_with(
            channel="C99999999", limit=20
        )

    def test_passes_limit_to_client(self):
        tool = _make_tool({"ok": True, "messages": []})
        tool.run(channel="C0", limit=5)
        call_kwargs = tool._client.conversations_history.call_args[1]
        assert call_kwargs["limit"] == 5

    def test_passes_oldest_when_provided(self):
        tool = _make_tool({"ok": True, "messages": []})
        tool.run(channel="C0", oldest="1700000000.000000")
        call_kwargs = tool._client.conversations_history.call_args[1]
        assert call_kwargs["oldest"] == "1700000000.000000"

    def test_passes_latest_when_provided(self):
        tool = _make_tool({"ok": True, "messages": []})
        tool.run(channel="C0", latest="1700001000.000000")
        call_kwargs = tool._client.conversations_history.call_args[1]
        assert call_kwargs["latest"] == "1700001000.000000"

    def test_oldest_not_passed_when_none(self):
        tool = _make_tool({"ok": True, "messages": []})
        tool.run(channel="C0")
        call_kwargs = tool._client.conversations_history.call_args[1]
        assert "oldest" not in call_kwargs

    def test_latest_not_passed_when_none(self):
        tool = _make_tool({"ok": True, "messages": []})
        tool.run(channel="C0")
        call_kwargs = tool._client.conversations_history.call_args[1]
        assert "latest" not in call_kwargs

    def test_returns_empty_list_when_no_messages_key(self):
        tool = _make_tool({"ok": True})
        result = tool.run(channel="C0")
        assert result == []

    def test_raises_on_api_error_flag(self):
        tool = _make_tool({"ok": False, "error": "channel_not_found"})
        with pytest.raises(ConversationHistoryError, match="channel_not_found"):
            tool.run(channel="C0")

    def test_raises_on_api_error_without_error_key(self):
        tool = _make_tool({"ok": False})
        with pytest.raises(ConversationHistoryError, match="unknown_error"):
            tool.run(channel="C0")

    def test_raises_when_client_raises(self):
        client = MagicMock()
        client.conversations_history.side_effect = RuntimeError("network failure")
        tool = ConversationHistoryTool(slack_client=client)
        with pytest.raises(ConversationHistoryError, match="network failure"):
            tool.run(channel="C0")


# ---------------------------------------------------------------------------
# ConversationHistoryTool.format_messages
# ---------------------------------------------------------------------------

class TestFormatMessages:
    def test_empty_messages_returns_placeholder(self):
        tool = _make_tool({"ok": True, "messages": []})
        assert tool.format_messages([]) == "(no messages)"

    def test_formats_user_messages(self):
        tool = _make_tool({"ok": True, "messages": []})
        formatted = tool.format_messages(_SAMPLE_MESSAGES)
        assert "U111" in formatted
        assert "Hello world" in formatted
        assert "U222" in formatted
        assert "Hi there" in formatted

    def test_each_message_on_own_line(self):
        tool = _make_tool({"ok": True, "messages": []})
        formatted = tool.format_messages(_SAMPLE_MESSAGES)
        lines = formatted.splitlines()
        assert len(lines) == len(_SAMPLE_MESSAGES)

    def test_uses_bot_id_when_no_user(self):
        messages = [{"ts": "1700000003.000300", "bot_id": "B001", "text": "I am a bot"}]
        tool = _make_tool({"ok": True, "messages": []})
        formatted = tool.format_messages(messages)
        assert "B001" in formatted

    def test_falls_back_to_unknown_sender(self):
        messages = [{"ts": "1700000004.000400", "text": "mystery message"}]
        tool = _make_tool({"ok": True, "messages": []})
        formatted = tool.format_messages(messages)
        assert "unknown" in formatted

    def test_timestamp_included_in_output(self):
        tool = _make_tool({"ok": True, "messages": []})
        formatted = tool.format_messages(_SAMPLE_MESSAGES)
        assert "1700000001.000100" in formatted
