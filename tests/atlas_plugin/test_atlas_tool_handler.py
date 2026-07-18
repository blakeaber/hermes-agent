"""
test_atlas_tool_handler.py
--------------------------
Unit tests for hermes_agent/handlers/atlas_tool_handler.py.

Coverage map
~~~~~~~~~~~~
TH-1  No config provided → recall() raises AtlasConfigError
TH-2  Invalid config (disabled) → recall() raises AtlasConfigError
TH-3  Invalid config (missing URL) → recall() raises AtlasConfigError
TH-4  Invalid config (missing key) → recall() raises AtlasConfigError
TH-5  Valid config + successful backend → recall() returns backend result
TH-6  Valid config + backend returns error JSON → recall() propagates it
TH-7  from_env() builds handler from environment variables
TH-8  from_env() with valid env → validate() passes, recall() delegates
TH-9  top_k parameter is forwarded to the underlying atlas_recall
TH-10 AtlasConfigError is raised before any network call is attempted
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from hermes_agent.handlers.atlas_tool_handler import AtlasToolHandler
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


_SAMPLE_RESULT = json.dumps([{"id": "doc-1", "text": "hello world", "score": 0.95}])
_ERROR_RESULT = json.dumps({"error": "Atlas plugin not installed"})


# ---------------------------------------------------------------------------
# TH-1  No config provided
# ---------------------------------------------------------------------------

class TestNoConfig:
    def test_recall_raises_atlas_config_error(self):
        handler = AtlasToolHandler()
        with pytest.raises(AtlasConfigError):
            handler.recall("some query")

    def test_error_message_is_informative(self):
        handler = AtlasToolHandler()
        with pytest.raises(AtlasConfigError, match="AtlasPluginConfig"):
            handler.recall("some query")

    def test_none_config_raises_before_network(self):
        """No network call should be made when config is None."""
        handler = AtlasToolHandler(config=None)
        with patch("gateway.run.atlas_recall") as mock_recall:
            with pytest.raises(AtlasConfigError):
                handler.recall("query")
            mock_recall.assert_not_called()


# ---------------------------------------------------------------------------
# TH-2  Invalid config - plugin disabled
# ---------------------------------------------------------------------------

class TestDisabledConfig:
    def test_recall_raises_when_disabled(self):
        cfg = _valid_config(atlas_plugin_enabled=False)
        handler = AtlasToolHandler(config=cfg)
        with pytest.raises(AtlasConfigError, match="ATLAS_PLUGIN_ENABLED"):
            handler.recall("query")

    def test_no_network_call_when_disabled(self):
        cfg = _valid_config(atlas_plugin_enabled=False)
        handler = AtlasToolHandler(config=cfg)
        with patch("gateway.run.atlas_recall") as mock_recall:
            with pytest.raises(AtlasConfigError):
                handler.recall("query")
            mock_recall.assert_not_called()


# ---------------------------------------------------------------------------
# TH-3  Invalid config - missing URL
# ---------------------------------------------------------------------------

class TestMissingUrl:
    def test_recall_raises_when_url_missing(self):
        cfg = _valid_config(atlas_api_url=None)
        handler = AtlasToolHandler(config=cfg)
        with pytest.raises(AtlasConfigError, match="ATLAS_API_URL"):
            handler.recall("query")

    def test_recall_raises_when_url_empty(self):
        cfg = _valid_config(atlas_api_url="")
        handler = AtlasToolHandler(config=cfg)
        with pytest.raises(AtlasConfigError, match="ATLAS_API_URL"):
            handler.recall("query")


# ---------------------------------------------------------------------------
# TH-4  Invalid config - missing key
# ---------------------------------------------------------------------------

class TestMissingKey:
    def test_recall_raises_when_key_missing(self):
        cfg = _valid_config(atlas_api_key=None)
        handler = AtlasToolHandler(config=cfg)
        with pytest.raises(AtlasConfigError, match="ATLAS_API_KEY"):
            handler.recall("query")

    def test_recall_raises_when_key_empty(self):
        cfg = _valid_config(atlas_api_key="")
        handler = AtlasToolHandler(config=cfg)
        with pytest.raises(AtlasConfigError, match="ATLAS_API_KEY"):
            handler.recall("query")


# ---------------------------------------------------------------------------
# TH-5  Valid config + successful backend
# ---------------------------------------------------------------------------

class TestValidConfigSuccess:
    def test_recall_returns_backend_result(self):
        cfg = _valid_config()
        handler = AtlasToolHandler(config=cfg)
        with patch("gateway.run.atlas_recall", return_value=_SAMPLE_RESULT) as mock_recall:
            result = handler.recall("find documents about AGE-469")
        assert result == _SAMPLE_RESULT
        mock_recall.assert_called_once_with("find documents about AGE-469", top_k=5)

    def test_result_is_valid_json(self):
        cfg = _valid_config()
        handler = AtlasToolHandler(config=cfg)
        with patch("gateway.run.atlas_recall", return_value=_SAMPLE_RESULT):
            result = handler.recall("query")
        parsed = json.loads(result)
        assert isinstance(parsed, list)
        assert parsed[0]["id"] == "doc-1"

    def test_does_not_raise_for_valid_config(self):
        cfg = _valid_config()
        handler = AtlasToolHandler(config=cfg)
        with patch("gateway.run.atlas_recall", return_value=_SAMPLE_RESULT):
            result = handler.recall("query")
        assert result is not None


# ---------------------------------------------------------------------------
# TH-6  Valid config + backend returns error JSON
# ---------------------------------------------------------------------------

class TestValidConfigBackendError:
    def test_recall_propagates_error_json(self):
        cfg = _valid_config()
        handler = AtlasToolHandler(config=cfg)
        with patch("gateway.run.atlas_recall", return_value=_ERROR_RESULT):
            result = handler.recall("query")
        assert result == _ERROR_RESULT

    def test_backend_error_does_not_raise(self):
        """Handler must not raise when the backend returns an error string."""
        cfg = _valid_config()
        handler = AtlasToolHandler(config=cfg)
        with patch("gateway.run.atlas_recall", return_value=_ERROR_RESULT):
            # Should not raise - error is encoded in the return value
            result = handler.recall("query")
        parsed = json.loads(result)
        assert "error" in parsed


# ---------------------------------------------------------------------------
# TH-7  from_env() factory
# ---------------------------------------------------------------------------

class TestFromEnv:
    def test_from_env_returns_handler_instance(self, monkeypatch):
        monkeypatch.setenv("ATLAS_API_URL", "https://atlas.example.com")
        monkeypatch.setenv("ATLAS_API_KEY", "env-key")
        monkeypatch.setenv("ATLAS_PLUGIN_ENABLED", "true")
        handler = AtlasToolHandler.from_env()
        assert isinstance(handler, AtlasToolHandler)

    def test_from_env_config_is_populated(self, monkeypatch):
        monkeypatch.setenv("ATLAS_API_URL", "https://atlas.example.com")
        monkeypatch.setenv("ATLAS_API_KEY", "env-key")
        monkeypatch.setenv("ATLAS_PLUGIN_ENABLED", "true")
        handler = AtlasToolHandler.from_env()
        assert handler._config is not None
        assert handler._config.atlas_api_url == "https://atlas.example.com"
        assert handler._config.atlas_api_key == "env-key"
        assert handler._config.atlas_plugin_enabled is True

    def test_from_env_disabled_raises_on_recall(self, monkeypatch):
        monkeypatch.setenv("ATLAS_API_URL", "https://atlas.example.com")
        monkeypatch.setenv("ATLAS_API_KEY", "env-key")
        monkeypatch.setenv("ATLAS_PLUGIN_ENABLED", "false")
        handler = AtlasToolHandler.from_env()
        with pytest.raises(AtlasConfigError):
            handler.recall("query")

    def test_from_env_missing_vars_raises_on_recall(self, monkeypatch):
        monkeypatch.delenv("ATLAS_API_URL", raising=False)
        monkeypatch.delenv("ATLAS_API_KEY", raising=False)
        monkeypatch.delenv("ATLAS_PLUGIN_ENABLED", raising=False)
        handler = AtlasToolHandler.from_env()
        with pytest.raises(AtlasConfigError):
            handler.recall("query")


# ---------------------------------------------------------------------------
# TH-8  from_env() with valid env → recall() delegates
# ---------------------------------------------------------------------------

class TestFromEnvValidRecall:
    def test_recall_delegates_when_env_valid(self, monkeypatch):
        monkeypatch.setenv("ATLAS_API_URL", "https://atlas.example.com")
        monkeypatch.setenv("ATLAS_API_KEY", "env-key")
        monkeypatch.setenv("ATLAS_PLUGIN_ENABLED", "true")
        handler = AtlasToolHandler.from_env()
        with patch("gateway.run.atlas_recall", return_value=_SAMPLE_RESULT) as mock_recall:
            result = handler.recall("env query")
        assert result == _SAMPLE_RESULT
        mock_recall.assert_called_once_with("env query", top_k=5)


# ---------------------------------------------------------------------------
# TH-9  top_k parameter forwarding
# ---------------------------------------------------------------------------

class TestTopKForwarding:
    def test_default_top_k_is_five(self):
        cfg = _valid_config()
        handler = AtlasToolHandler(config=cfg)
        with patch("gateway.run.atlas_recall", return_value=_SAMPLE_RESULT) as mock_recall:
            handler.recall("query")
        _, kwargs = mock_recall.call_args
        assert kwargs["top_k"] == 5

    def test_custom_top_k_is_forwarded(self):
        cfg = _valid_config()
        handler = AtlasToolHandler(config=cfg)
        with patch("gateway.run.atlas_recall", return_value=_SAMPLE_RESULT) as mock_recall:
            handler.recall("query", top_k=10)
        _, kwargs = mock_recall.call_args
        assert kwargs["top_k"] == 10

    def test_top_k_one_is_forwarded(self):
        cfg = _valid_config()
        handler = AtlasToolHandler(config=cfg)
        with patch("gateway.run.atlas_recall", return_value=_SAMPLE_RESULT) as mock_recall:
            handler.recall("query", top_k=1)
        _, kwargs = mock_recall.call_args
        assert kwargs["top_k"] == 1

    def test_top_k_large_value_is_forwarded(self):
        cfg = _valid_config()
        handler = AtlasToolHandler(config=cfg)
        with patch("gateway.run.atlas_recall", return_value=_SAMPLE_RESULT) as mock_recall:
            handler.recall("query", top_k=100)
        _, kwargs = mock_recall.call_args
        assert kwargs["top_k"] == 100


# ---------------------------------------------------------------------------
# TH-10  AtlasConfigError raised before any network call
# ---------------------------------------------------------------------------

class TestConfigErrorBeforeNetwork:
    @pytest.mark.parametrize("bad_config", [
        AtlasPluginConfig(),  # all defaults: None/False
        _valid_config(atlas_plugin_enabled=False),
        _valid_config(atlas_api_url=None),
        _valid_config(atlas_api_key=None),
    ])
    def test_no_network_call_for_invalid_config(self, bad_config):
        handler = AtlasToolHandler(config=bad_config)
        with patch("gateway.run.atlas_recall") as mock_recall:
            with pytest.raises(AtlasConfigError):
                handler.recall("query")
            mock_recall.assert_not_called()

    def test_network_call_made_only_for_valid_config(self):
        cfg = _valid_config()
        handler = AtlasToolHandler(config=cfg)
        with patch("gateway.run.atlas_recall", return_value=_SAMPLE_RESULT) as mock_recall:
            handler.recall("query")
        mock_recall.assert_called_once()
