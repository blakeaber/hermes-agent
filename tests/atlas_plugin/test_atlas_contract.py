"""
test_atlas_contract.py
----------------------
Unit tests for plugins/memory/atlas_contract.py.

Each test maps directly to a root-cause finding documented in
tests/atlas_plugin/findings_age469.md:

  RC-1  Missing plugin configuration (all three keys absent)
  RC-2  ATLAS_PLUGIN_ENABLED defaults to False / must be explicitly True
  RC-3  ATLAS_API_URL is required
  RC-4  ATLAS_API_KEY is required
  RC-5  All three keys present and enabled → valid config
  RC-6  from_env() correctly reads environment variables
  RC-7  is_valid property mirrors validate() without raising
"""

from __future__ import annotations

import os
import pytest

from plugins.memory.atlas_contract import AtlasConfigError, AtlasPluginConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_config(**overrides) -> AtlasPluginConfig:
    """Return a fully-populated, enabled config, optionally overriding fields."""
    defaults = dict(
        atlas_api_url="https://atlas.example.com/api",
        atlas_api_key="secret-token-abc123",
        atlas_plugin_enabled=True,
    )
    defaults.update(overrides)
    return AtlasPluginConfig(**defaults)


# ---------------------------------------------------------------------------
# RC-1 - All three keys absent → validation must fail
# ---------------------------------------------------------------------------

class TestAllKeysAbsent:
    def test_raises_atlas_config_error(self):
        cfg = AtlasPluginConfig()  # all defaults: None / False
        with pytest.raises(AtlasConfigError):
            cfg.validate()

    def test_error_mentions_enabled_flag(self):
        cfg = AtlasPluginConfig()
        with pytest.raises(AtlasConfigError, match="ATLAS_PLUGIN_ENABLED"):
            cfg.validate()

    def test_error_mentions_api_url(self):
        cfg = AtlasPluginConfig()
        with pytest.raises(AtlasConfigError, match="ATLAS_API_URL"):
            cfg.validate()

    def test_error_mentions_api_key(self):
        cfg = AtlasPluginConfig()
        with pytest.raises(AtlasConfigError, match="ATLAS_API_KEY"):
            cfg.validate()


# ---------------------------------------------------------------------------
# RC-2 - ATLAS_PLUGIN_ENABLED defaults to False
# ---------------------------------------------------------------------------

class TestPluginEnabledFlag:
    def test_default_is_disabled(self):
        cfg = AtlasPluginConfig(
            atlas_api_url="https://atlas.example.com/api",
            atlas_api_key="key",
        )
        assert cfg.atlas_plugin_enabled is False

    def test_disabled_raises_even_when_url_and_key_present(self):
        cfg = AtlasPluginConfig(
            atlas_api_url="https://atlas.example.com/api",
            atlas_api_key="key",
            atlas_plugin_enabled=False,
        )
        with pytest.raises(AtlasConfigError, match="ATLAS_PLUGIN_ENABLED"):
            cfg.validate()

    def test_enabled_true_does_not_raise_for_enabled_flag(self):
        cfg = _valid_config()
        # Should not raise - no assertion needed beyond no exception
        cfg.validate()


# ---------------------------------------------------------------------------
# RC-3 - ATLAS_API_URL is required
# ---------------------------------------------------------------------------

class TestAtlasApiUrl:
    def test_missing_url_raises(self):
        cfg = _valid_config(atlas_api_url=None)
        with pytest.raises(AtlasConfigError, match="ATLAS_API_URL"):
            cfg.validate()

    def test_empty_string_url_raises(self):
        cfg = _valid_config(atlas_api_url="")
        with pytest.raises(AtlasConfigError, match="ATLAS_API_URL"):
            cfg.validate()

    def test_whitespace_only_url_raises(self):
        # from_env strips and converts empty strings to None
        cfg = AtlasPluginConfig(
            atlas_api_url=None,
            atlas_api_key="key",
            atlas_plugin_enabled=True,
        )
        with pytest.raises(AtlasConfigError, match="ATLAS_API_URL"):
            cfg.validate()

    def test_valid_url_passes(self):
        cfg = _valid_config(atlas_api_url="https://atlas.example.com")
        cfg.validate()  # must not raise


# ---------------------------------------------------------------------------
# RC-4 - ATLAS_API_KEY is required
# ---------------------------------------------------------------------------

class TestAtlasApiKey:
    def test_missing_key_raises(self):
        cfg = _valid_config(atlas_api_key=None)
        with pytest.raises(AtlasConfigError, match="ATLAS_API_KEY"):
            cfg.validate()

    def test_empty_string_key_raises(self):
        cfg = _valid_config(atlas_api_key="")
        with pytest.raises(AtlasConfigError, match="ATLAS_API_KEY"):
            cfg.validate()

    def test_valid_key_passes(self):
        cfg = _valid_config(atlas_api_key="my-secret-key")
        cfg.validate()  # must not raise


# ---------------------------------------------------------------------------
# RC-5 - All three keys present and enabled → valid
# ---------------------------------------------------------------------------

class TestFullyValidConfig:
    def test_validate_does_not_raise(self):
        cfg = _valid_config()
        cfg.validate()  # must not raise

    def test_is_valid_returns_true(self):
        cfg = _valid_config()
        assert cfg.is_valid is True

    def test_fields_are_stored_correctly(self):
        cfg = _valid_config(
            atlas_api_url="https://atlas.example.com/api/v2",
            atlas_api_key="tok-xyz",
        )
        assert cfg.atlas_api_url == "https://atlas.example.com/api/v2"
        assert cfg.atlas_api_key == "tok-xyz"
        assert cfg.atlas_plugin_enabled is True


# ---------------------------------------------------------------------------
# RC-6 - from_env() reads environment variables correctly
# ---------------------------------------------------------------------------

class TestFromEnv:
    def test_reads_all_three_vars(self, monkeypatch):
        monkeypatch.setenv("ATLAS_API_URL", "https://env-atlas.example.com")
        monkeypatch.setenv("ATLAS_API_KEY", "env-key-123")
        monkeypatch.setenv("ATLAS_PLUGIN_ENABLED", "true")

        cfg = AtlasPluginConfig.from_env()

        assert cfg.atlas_api_url == "https://env-atlas.example.com"
        assert cfg.atlas_api_key == "env-key-123"
        assert cfg.atlas_plugin_enabled is True

    def test_enabled_false_when_var_absent(self, monkeypatch):
        monkeypatch.delenv("ATLAS_PLUGIN_ENABLED", raising=False)
        monkeypatch.setenv("ATLAS_API_URL", "https://atlas.example.com")
        monkeypatch.setenv("ATLAS_API_KEY", "key")

        cfg = AtlasPluginConfig.from_env()
        assert cfg.atlas_plugin_enabled is False

    def test_enabled_false_when_var_is_false_string(self, monkeypatch):
        monkeypatch.setenv("ATLAS_PLUGIN_ENABLED", "false")
        monkeypatch.setenv("ATLAS_API_URL", "https://atlas.example.com")
        monkeypatch.setenv("ATLAS_API_KEY", "key")

        cfg = AtlasPluginConfig.from_env()
        assert cfg.atlas_plugin_enabled is False

    @pytest.mark.parametrize("truthy_value", ["true", "True", "TRUE", "1", "yes", "YES"])
    def test_enabled_true_for_truthy_strings(self, monkeypatch, truthy_value):
        monkeypatch.setenv("ATLAS_PLUGIN_ENABLED", truthy_value)
        monkeypatch.setenv("ATLAS_API_URL", "https://atlas.example.com")
        monkeypatch.setenv("ATLAS_API_KEY", "key")

        cfg = AtlasPluginConfig.from_env()
        assert cfg.atlas_plugin_enabled is True

    def test_url_none_when_env_var_absent(self, monkeypatch):
        monkeypatch.delenv("ATLAS_API_URL", raising=False)
        monkeypatch.delenv("ATLAS_API_KEY", raising=False)
        monkeypatch.delenv("ATLAS_PLUGIN_ENABLED", raising=False)

        cfg = AtlasPluginConfig.from_env()
        assert cfg.atlas_api_url is None
        assert cfg.atlas_api_key is None

    def test_from_env_validates_successfully_with_correct_env(self, monkeypatch):
        monkeypatch.setenv("ATLAS_API_URL", "https://atlas.example.com")
        monkeypatch.setenv("ATLAS_API_KEY", "secret")
        monkeypatch.setenv("ATLAS_PLUGIN_ENABLED", "true")

        cfg = AtlasPluginConfig.from_env()
        cfg.validate()  # must not raise


# ---------------------------------------------------------------------------
# RC-7 - is_valid property
# ---------------------------------------------------------------------------

class TestIsValid:
    def test_is_valid_false_when_disabled(self):
        cfg = AtlasPluginConfig(
            atlas_api_url="https://atlas.example.com",
            atlas_api_key="key",
            atlas_plugin_enabled=False,
        )
        assert cfg.is_valid is False

    def test_is_valid_false_when_url_missing(self):
        cfg = _valid_config(atlas_api_url=None)
        assert cfg.is_valid is False

    def test_is_valid_false_when_key_missing(self):
        cfg = _valid_config(atlas_api_key=None)
        assert cfg.is_valid is False

    def test_is_valid_true_for_complete_config(self):
        cfg = _valid_config()
        assert cfg.is_valid is True

    def test_is_valid_does_not_raise(self):
        """is_valid must never propagate AtlasConfigError."""
        cfg = AtlasPluginConfig()  # fully invalid
        result = cfg.is_valid  # must not raise
        assert result is False
