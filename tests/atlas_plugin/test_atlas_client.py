"""
test_atlas_client.py
--------------------
Unit tests for plugins/memory/atlas_client.py.

All tests use monkeypatching / direct patching of ``AtlasClient._request``
to avoid real network calls.  No external services are required.

Test groups
~~~~~~~~~~~
  TC-1  Constructor rejects invalid / disabled config
  TC-2  Constructor accepts valid config
  TC-3  _build_url constructs correct URLs
  TC-4  _auth_headers returns correct Authorization header
  TC-5  get_findings returns parsed JSON list
  TC-6  get_findings raises AtlasClientError on HTTP error
  TC-7  get_findings raises AtlasClientError on network failure
  TC-8  get_findings raises AtlasClientError on non-JSON response
  TC-9  health_check returns True on success
  TC-10 health_check returns False on AtlasClientError
"""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from plugins.memory.atlas_client import AtlasClient, AtlasClientError
from plugins.memory.atlas_contract import AtlasConfigError, AtlasPluginConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_config(**overrides) -> AtlasPluginConfig:
    defaults = dict(
        atlas_api_url="https://atlas.example.com/api",
        atlas_api_key="secret-token-abc123",
        atlas_plugin_enabled=True,
    )
    defaults.update(overrides)
    return AtlasPluginConfig(**defaults)


def _make_client(**overrides) -> AtlasClient:
    return AtlasClient(_valid_config(**overrides))


# ---------------------------------------------------------------------------
# TC-1 - Constructor rejects invalid / disabled config
# ---------------------------------------------------------------------------

class TestConstructorRejectsInvalidConfig:
    def test_raises_when_plugin_disabled(self):
        cfg = AtlasPluginConfig(
            atlas_api_url="https://atlas.example.com",
            atlas_api_key="key",
            atlas_plugin_enabled=False,
        )
        with pytest.raises(AtlasConfigError):
            AtlasClient(cfg)

    def test_raises_when_url_missing(self):
        cfg = AtlasPluginConfig(
            atlas_api_url=None,
            atlas_api_key="key",
            atlas_plugin_enabled=True,
        )
        with pytest.raises(AtlasConfigError):
            AtlasClient(cfg)

    def test_raises_when_key_missing(self):
        cfg = AtlasPluginConfig(
            atlas_api_url="https://atlas.example.com",
            atlas_api_key=None,
            atlas_plugin_enabled=True,
        )
        with pytest.raises(AtlasConfigError):
            AtlasClient(cfg)

    def test_raises_for_fully_empty_config(self):
        with pytest.raises(AtlasConfigError):
            AtlasClient(AtlasPluginConfig())


# ---------------------------------------------------------------------------
# TC-2 - Constructor accepts valid config
# ---------------------------------------------------------------------------

class TestConstructorAcceptsValidConfig:
    def test_does_not_raise_for_valid_config(self):
        client = _make_client()
        assert client is not None

    def test_stores_config(self):
        cfg = _valid_config()
        client = AtlasClient(cfg)
        assert client._config is cfg


# ---------------------------------------------------------------------------
# TC-3 - _build_url constructs correct URLs
# ---------------------------------------------------------------------------

class TestBuildUrl:
    def test_appends_path_to_base(self):
        client = _make_client(atlas_api_url="https://atlas.example.com/api")
        url = client._build_url("/findings")
        assert url == "https://atlas.example.com/api/findings"

    def test_handles_base_without_trailing_slash(self):
        client = _make_client(atlas_api_url="https://atlas.example.com/api")
        url = client._build_url("/health")
        assert url == "https://atlas.example.com/api/health"

    def test_handles_base_with_trailing_slash(self):
        client = _make_client(atlas_api_url="https://atlas.example.com/api/")
        url = client._build_url("/findings")
        assert url == "https://atlas.example.com/api/findings"

    def test_handles_path_without_leading_slash(self):
        client = _make_client(atlas_api_url="https://atlas.example.com/api")
        url = client._build_url("findings")
        assert url == "https://atlas.example.com/api/findings"

    def test_default_findings_path(self):
        client = _make_client(atlas_api_url="https://atlas.example.com/api")
        url = client._build_url("/findings")
        assert "findings" in url


# ---------------------------------------------------------------------------
# TC-4 - _auth_headers returns correct Authorization header
# ---------------------------------------------------------------------------

class TestAuthHeaders:
    def test_contains_bearer_token(self):
        client = _make_client(atlas_api_key="my-secret-key")
        headers = client._auth_headers()
        assert headers["Authorization"] == "Bearer my-secret-key"

    def test_contains_accept_json(self):
        client = _make_client()
        headers = client._auth_headers()
        assert headers["Accept"] == "application/json"

    def test_contains_content_type_json(self):
        client = _make_client()
        headers = client._auth_headers()
        assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# TC-5 - get_findings returns parsed JSON list
# ---------------------------------------------------------------------------

class TestGetFindingsSuccess:
    def test_returns_list_of_findings(self):
        findings = [{"id": "F-001", "severity": "high"}, {"id": "F-002", "severity": "low"}]
        client = _make_client()
        client._request = MagicMock(return_value=json.dumps(findings))

        result = client.get_findings()

        assert result == findings

    def test_calls_request_with_correct_url(self):
        client = _make_client(atlas_api_url="https://atlas.example.com/api")
        client._request = MagicMock(return_value="[]")

        client.get_findings("/findings")

        called_url = client._request.call_args[0][0]
        assert "findings" in called_url

    def test_calls_request_with_auth_headers(self):
        client = _make_client(atlas_api_key="tok-xyz")
        client._request = MagicMock(return_value="[]")

        client.get_findings()

        called_headers = client._request.call_args[0][1]
        assert called_headers["Authorization"] == "Bearer tok-xyz"

    def test_returns_empty_list_for_empty_response(self):
        client = _make_client()
        client._request = MagicMock(return_value="[]")

        result = client.get_findings()

        assert result == []

    def test_uses_default_findings_path(self):
        client = _make_client(atlas_api_url="https://atlas.example.com/api")
        client._request = MagicMock(return_value="[]")

        client.get_findings()

        called_url = client._request.call_args[0][0]
        assert called_url.endswith("findings")


# ---------------------------------------------------------------------------
# TC-6 - get_findings raises AtlasClientError on HTTP error
# ---------------------------------------------------------------------------

class TestGetFindingsHttpError:
    def test_raises_atlas_client_error_on_http_error(self):
        client = _make_client()
        client._request = MagicMock(
            side_effect=AtlasClientError("HTTP error 403")
        )
        with pytest.raises(AtlasClientError):
            client.get_findings()

    def test_error_message_contains_context(self):
        client = _make_client()
        client._request = MagicMock(
            side_effect=AtlasClientError("Atlas API HTTP error 404 for https://atlas.example.com/api/findings: Not Found")
        )
        with pytest.raises(AtlasClientError, match="404"):
            client.get_findings()


# ---------------------------------------------------------------------------
# TC-7 - get_findings raises AtlasClientError on network failure
# ---------------------------------------------------------------------------

class TestGetFindingsNetworkFailure:
    def test_raises_atlas_client_error_on_network_failure(self):
        client = _make_client()
        client._request = MagicMock(
            side_effect=AtlasClientError("Atlas API unreachable")
        )
        with pytest.raises(AtlasClientError, match="unreachable"):
            client.get_findings()

    def test_request_method_wraps_url_error(self):
        """Verify _request itself converts URLError to AtlasClientError."""
        client = _make_client(atlas_api_url="https://atlas.example.com/api")
        url_error = urllib.error.URLError("Connection refused")

        with patch("urllib.request.urlopen", side_effect=url_error):
            with pytest.raises(AtlasClientError, match="unreachable"):
                client._request(
                    "https://atlas.example.com/api/findings",
                    client._auth_headers(),
                )

    def test_request_method_wraps_http_error(self):
        """Verify _request itself converts HTTPError to AtlasClientError."""
        client = _make_client(atlas_api_url="https://atlas.example.com/api")
        http_error = urllib.error.HTTPError(
            url="https://atlas.example.com/api/findings",
            code=500,
            msg="Internal Server Error",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )

        with patch("urllib.request.urlopen", side_effect=http_error):
            with pytest.raises(AtlasClientError, match="500"):
                client._request(
                    "https://atlas.example.com/api/findings",
                    client._auth_headers(),
                )


# ---------------------------------------------------------------------------
# TC-8 - get_findings raises AtlasClientError on non-JSON response
# ---------------------------------------------------------------------------

class TestGetFindingsNonJsonResponse:
    def test_raises_on_html_response(self):
        client = _make_client()
        client._request = MagicMock(return_value="<html>Not Found</html>")

        with pytest.raises(AtlasClientError, match="non-JSON"):
            client.get_findings()

    def test_raises_on_empty_string_response(self):
        client = _make_client()
        client._request = MagicMock(return_value="")

        with pytest.raises(AtlasClientError):
            client.get_findings()

    def test_raises_on_plain_text_response(self):
        client = _make_client()
        client._request = MagicMock(return_value="Internal Server Error")

        with pytest.raises(AtlasClientError):
            client.get_findings()


# ---------------------------------------------------------------------------
# TC-9 - health_check returns True on success
# ---------------------------------------------------------------------------

class TestHealthCheckSuccess:
    def test_returns_true_when_request_succeeds(self):
        client = _make_client()
        client._request = MagicMock(return_value='{"status": "ok"}')

        assert client.health_check() is True

    def test_calls_health_endpoint(self):
        client = _make_client(atlas_api_url="https://atlas.example.com/api")
        client._request = MagicMock(return_value="{}")

        client.health_check()

        called_url = client._request.call_args[0][0]
        assert "health" in called_url


# ---------------------------------------------------------------------------
# TC-10 - health_check returns False on AtlasClientError
# ---------------------------------------------------------------------------

class TestHealthCheckFailure:
    def test_returns_false_on_atlas_client_error(self):
        client = _make_client()
        client._request = MagicMock(
            side_effect=AtlasClientError("connection refused")
        )

        assert client.health_check() is False

    def test_does_not_raise_on_network_failure(self):
        """health_check must never propagate AtlasClientError."""
        client = _make_client()
        client._request = MagicMock(
            side_effect=AtlasClientError("timeout")
        )

        result = client.health_check()  # must not raise
        assert result is False

    def test_returns_false_on_http_error(self):
        client = _make_client()
        client._request = MagicMock(
            side_effect=AtlasClientError("HTTP error 503")
        )

        assert client.health_check() is False
