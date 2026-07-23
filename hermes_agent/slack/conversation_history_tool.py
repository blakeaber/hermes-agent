"""
Tool for fetching Slack conversation history.

Provides a LangChain-compatible tool that retrieves messages from a Slack
channel using the Slack Web API (conversations.history).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConversationHistoryInput(BaseModel):
    """Input schema for the ConversationHistoryTool."""

    channel: str = Field(
        ...,
        description="The Slack channel ID to fetch history from (e.g. 'C01234567').",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Maximum number of messages to return (1–200, default 20).",
    )
    oldest: Optional[str] = Field(
        default=None,
        description=(
            "Only messages after this Unix timestamp (as a string) are returned."
        ),
    )
    latest: Optional[str] = Field(
        default=None,
        description=(
            "Only messages before this Unix timestamp (as a string) are returned."
        ),
    )


class ConversationHistoryTool:
    """
    Fetches the message history of a Slack channel.

    Parameters
    ----------
    slack_client:
        An initialised ``slack_sdk.WebClient`` (or any object that exposes a
        ``conversations_history`` method with the same signature).
    """

    name: str = "slack_conversation_history"
    description: str = (
        "Retrieve recent messages from a Slack channel. "
        "Provide the channel ID and optionally a message limit and time bounds."
    )
    args_schema = ConversationHistoryInput

    def __init__(self, slack_client: Any) -> None:
        self._client = slack_client

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def run(
        self,
        channel: str,
        limit: int = 20,
        oldest: Optional[str] = None,
        latest: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch messages from *channel* and return them as a list of dicts.

        Each dict contains at minimum ``ts`` (timestamp), ``user`` (or
        ``bot_id``), and ``text`` keys as returned by the Slack API.

        Raises
        ------
        ConversationHistoryError
            If the Slack API call fails or returns ``ok: false``.
        """
        kwargs: Dict[str, Any] = {
            "channel": channel,
            "limit": limit,
        }
        if oldest is not None:
            kwargs["oldest"] = oldest
        if latest is not None:
            kwargs["latest"] = latest

        try:
            response = self._client.conversations_history(**kwargs)
        except Exception as exc:
            raise ConversationHistoryError(
                f"Slack API call failed for channel '{channel}': {exc}"
            ) from exc

        if not response.get("ok"):
            error = response.get("error", "unknown_error")
            raise ConversationHistoryError(
                f"Slack API returned an error for channel '{channel}': {error}"
            )

        messages: List[Dict[str, Any]] = response.get("messages", [])
        return messages

    def format_messages(self, messages: List[Dict[str, Any]]) -> str:
        """
        Return a human-readable string representation of *messages*.

        Useful for feeding conversation history directly into an LLM prompt.
        """
        if not messages:
            return "(no messages)"

        lines: List[str] = []
        for msg in messages:
            sender = msg.get("user") or msg.get("bot_id") or "unknown"
            ts = msg.get("ts", "")
            text = msg.get("text", "")
            lines.append(f"[{ts}] {sender}: {text}")
        return "\n".join(lines)


class ConversationHistoryError(Exception):
    """Raised when the Slack conversation history request fails."""
