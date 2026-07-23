"""Utilities for posting messages back to a Slack response_url."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ResponseType(str, Enum):
    """Slack response_url visibility options."""

    IN_CHANNEL = "in_channel"
    EPHEMERAL = "ephemeral"


@dataclass
class SlackMessage:
    """A message payload to be sent to a Slack response_url.

    Parameters
    ----------
    text:
        The plain-text fallback / primary message body.
    response_type:
        Whether the message is visible to everyone in the channel
        (``in_channel``) or only to the invoking user (``ephemeral``).
        Defaults to ``ephemeral``.
    replace_original:
        When ``True`` the original message that triggered the interaction
        is replaced by this response.
    delete_original:
        When ``True`` the original message is deleted.  Cannot be combined
        with ``replace_original``.
    blocks:
        Optional list of Slack Block Kit block objects.
    attachments:
        Optional list of legacy Slack attachment objects.
    """

    text: str
    response_type: ResponseType = ResponseType.EPHEMERAL
    replace_original: bool = False
    delete_original: bool = False
    blocks: List[Dict[str, Any]] = field(default_factory=list)
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a dict suitable for JSON-encoding and POSTing."""
        payload: Dict[str, Any] = {
            "text": self.text,
            "response_type": self.response_type.value,
            "replace_original": self.replace_original,
            "delete_original": self.delete_original,
        }
        if self.blocks:
            payload["blocks"] = self.blocks
        if self.attachments:
            payload["attachments"] = self.attachments
        return payload


class ResponseUrlError(Exception):
    """Raised when a POST to a Slack response_url fails."""

    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def post_message(
    response_url: str,
    message: SlackMessage,
    *,
    timeout: int = 10,
) -> None:
    """POST *message* to the given Slack *response_url*.

    Parameters
    ----------
    response_url:
        The ``response_url`` string received from Slack (must be HTTPS).
    message:
        The :class:`SlackMessage` to send.
    timeout:
        Socket timeout in seconds (default ``10``).

    Raises
    ------
    ValueError
        If *response_url* is empty or does not start with ``https://``.
    ResponseUrlError
        If the HTTP request fails or Slack returns a non-200 status.
    """
    if not response_url:
        raise ValueError("response_url must not be empty")
    if not response_url.startswith("https://"):
        raise ValueError("response_url must start with 'https://'")

    body = json.dumps(message.to_dict()).encode("utf-8")
    request = Request(
        response_url,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            status = response.status
            if status != 200:
                raise ResponseUrlError(
                    f"Slack returned unexpected status {status}",
                    status_code=status,
                )
    except HTTPError as exc:
        raise ResponseUrlError(
            f"HTTP error posting to response_url: {exc}",
            status_code=exc.code,
        ) from exc
    except URLError as exc:
        raise ResponseUrlError(
            f"URL error posting to response_url: {exc.reason}"
        ) from exc
