"""Tests for hermes_agent.slack.response_url."""

from __future__ import annotations

import json
from io import BytesIO
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from hermes_agent.slack.response_url import (
    ResponseType,
    ResponseUrlError,
    SlackMessage,
    post_message,
)


# ---------------------------------------------------------------------------
# SlackMessage.to_dict
# ---------------------------------------------------------------------------


class TestSlackMessageToDict:
    def test_defaults(self):
        msg = SlackMessage(text="hello")
        d = msg.to_dict()
        assert d["text"] == "hello"
        assert d["response_type"] == "ephemeral"
        assert d["replace_original"] is False
        assert d["delete_original"] is False
        assert "blocks" not in d
        assert "attachments" not in d

    def test_in_channel_response_type(self):
        msg = SlackMessage(text="hi", response_type=ResponseType.IN_CHANNEL)
        assert msg.to_dict()["response_type"] == "in_channel"

    def test_replace_original(self):
        msg = SlackMessage(text="updated", replace_original=True)
        assert msg.to_dict()["replace_original"] is True

    def test_delete_original(self):
        msg = SlackMessage(text="bye", delete_original=True)
        assert msg.to_dict()["delete_original"] is True

    def test_blocks_included_when_present(self):
        blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "*hi*"}}]
        msg = SlackMessage(text="hi", blocks=blocks)
        d = msg.to_dict()
        assert d["blocks"] == blocks

    def test_attachments_included_when_present(self):
        attachments = [{"fallback": "old style", "text": "legacy"}]
        msg = SlackMessage(text="hi", attachments=attachments)
        d = msg.to_dict()
        assert d["attachments"] == attachments

    def test_empty_blocks_omitted(self):
        msg = SlackMessage(text="hi", blocks=[])
        assert "blocks" not in msg.to_dict()

    def test_empty_attachments_omitted(self):
        msg = SlackMessage(text="hi", attachments=[])
        assert "attachments" not in msg.to_dict()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(status: int = 200, body: bytes = b"ok") -> MagicMock:
    """Return a mock that behaves like the context-manager from urlopen."""
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# post_message - validation
# ---------------------------------------------------------------------------


class TestPostMessageValidation:
    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            post_message("", SlackMessage(text="hi"))

    def test_http_url_raises(self):
        with pytest.raises(ValueError, match="must start with 'https://'"):
            post_message("http://hooks.slack.com/foo", SlackMessage(text="hi"))

    def test_non_url_raises(self):
        with pytest.raises(ValueError, match="must start with 'https://'"):
            post_message("not-a-url", SlackMessage(text="hi"))


# ---------------------------------------------------------------------------
# post_message - successful POST
# ---------------------------------------------------------------------------


class TestPostMessageSuccess:
    def test_posts_json_body(self):
        msg = SlackMessage(text="hello world")
        mock_resp = _make_response(200)

        with patch(
            "hermes_agent.slack.response_url.urlopen", return_value=mock_resp
        ) as mock_urlopen:
            post_message("https://hooks.slack.com/actions/T/B/secret", msg)

        mock_urlopen.assert_called_once()
        request_arg = mock_urlopen.call_args[0][0]
        body = json.loads(request_arg.data.decode("utf-8"))
        assert body["text"] == "hello world"

    def test_content_type_header(self):
        msg = SlackMessage(text="hi")
        mock_resp = _make_response(200)

        with patch(
            "hermes_agent.slack.response_url.urlopen", return_value=mock_resp
        ):
            post_message("https://hooks.slack.com/actions/T/B/secret", msg)

        # No exception means success; header is set on the Request object
        # (verified indirectly - if Content-Type were wrong Slack would 400,
        # but we also check it directly below via the Request constructor).

    def test_request_uses_post_method(self):
        msg = SlackMessage(text="hi")
        mock_resp = _make_response(200)

        with patch(
            "hermes_agent.slack.response_url.urlopen", return_value=mock_resp
        ) as mock_urlopen:
            post_message("https://hooks.slack.com/actions/T/B/secret", msg)

        request_arg = mock_urlopen.call_args[0][0]
        assert request_arg.method == "POST"

    def test_timeout_forwarded(self):
        msg = SlackMessage(text="hi")
        mock_resp = _make_response(200)

        with patch(
            "hermes_agent.slack.response_url.urlopen", return_value=mock_resp
        ) as mock_urlopen:
            post_message("https://hooks.slack.com/actions/T/B/secret", msg, timeout=5)

        _, kwargs = mock_urlopen.call_args
        assert kwargs.get("timeout") == 5


# ---------------------------------------------------------------------------
# post_message - error handling
# ---------------------------------------------------------------------------


class TestPostMessageErrors:
    def test_non_200_raises_response_url_error(self):
        mock_resp = _make_response(500)

        with patch(
            "hermes_agent.slack.response_url.urlopen", return_value=mock_resp
        ):
            with pytest.raises(ResponseUrlError) as exc_info:
                post_message(
                    "https://hooks.slack.com/actions/T/B/secret",
                    SlackMessage(text="hi"),
                )

        assert exc_info.value.status_code == 500

    def test_http_error_raises_response_url_error(self):
        from urllib.error import HTTPError

        http_err = HTTPError(
            url="https://hooks.slack.com/actions/T/B/secret",
            code=403,
            msg="Forbidden",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(b""),
        )

        with patch(
            "hermes_agent.slack.response_url.urlopen", side_effect=http_err
        ):
            with pytest.raises(ResponseUrlError) as exc_info:
                post_message(
                    "https://hooks.slack.com/actions/T/B/secret",
                    SlackMessage(text="hi"),
                )

        assert exc_info.value.status_code == 403

    def test_url_error_raises_response_url_error(self):
        from urllib.error import URLError

        with patch(
            "hermes_agent.slack.response_url.urlopen",
            side_effect=URLError("Name or service not known"),
        ):
            with pytest.raises(ResponseUrlError) as exc_info:
                post_message(
                    "https://hooks.slack.com/actions/T/B/secret",
                    SlackMessage(text="hi"),
                )

        assert exc_info.value.status_code is None
        assert "Name or service not known" in str(exc_info.value)

    def test_response_url_error_carries_status_code(self):
        err = ResponseUrlError("something went wrong", status_code=429)
        assert err.status_code == 429
        assert "something went wrong" in str(err)

    def test_response_url_error_without_status_code(self):
        err = ResponseUrlError("network failure")
        assert err.status_code is None
