"""
Tests for Slack home channel configuration in gateway/config.py.

Covers:
- SLACK_HOME_CHANNEL env var wires up a HomeChannel on the Slack PlatformConfig
- SLACK_HOME_CHANNEL_NAME and SLACK_HOME_CHANNEL_THREAD_ID are respected
- No home channel is created when SLACK_HOME_CHANNEL is set but Slack is absent
- HomeChannel round-trips through to_dict() / from_dict()
- GatewayConfig.get_home_channel() returns the correct channel for Slack
"""

import pytest

from gateway.config import (
    GatewayConfig,
    HomeChannel,
    Platform,
    PlatformConfig,
    _apply_env_overrides,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slack_config(enabled: bool = True, token: str = "xoxb-test") -> PlatformConfig:
    """Return a minimal PlatformConfig for Slack."""
    return PlatformConfig(enabled=enabled, token=token)


def _config_with_slack(**kwargs) -> GatewayConfig:
    """Return a GatewayConfig that already has a Slack platform entry."""
    cfg = GatewayConfig()
    cfg.platforms[Platform.SLACK] = _slack_config(**kwargs)
    return cfg


# ---------------------------------------------------------------------------
# SLACK_HOME_CHANNEL env var
# ---------------------------------------------------------------------------

class TestSlackHomeChannelEnvVar:

    def test_sets_home_channel_when_slack_present(self, monkeypatch):
        monkeypatch.setenv("SLACK_HOME_CHANNEL", "C0123456789")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        cfg = _config_with_slack()
        _apply_env_overrides(cfg)

        hc = cfg.platforms[Platform.SLACK].home_channel
        assert hc is not None
        assert hc.chat_id == "C0123456789"
        assert hc.platform == Platform.SLACK

    def test_default_name_is_empty_string(self, monkeypatch):
        """SLACK_HOME_CHANNEL_NAME defaults to '' (not 'Home') for Slack."""
        monkeypatch.setenv("SLACK_HOME_CHANNEL", "C0123456789")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.delenv("SLACK_HOME_CHANNEL_NAME", raising=False)
        cfg = _config_with_slack()
        _apply_env_overrides(cfg)

        hc = cfg.platforms[Platform.SLACK].home_channel
        assert hc.name == ""

    def test_custom_name_is_respected(self, monkeypatch):
        monkeypatch.setenv("SLACK_HOME_CHANNEL", "C0123456789")
        monkeypatch.setenv("SLACK_HOME_CHANNEL_NAME", "ops-alerts")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        cfg = _config_with_slack()
        _apply_env_overrides(cfg)

        hc = cfg.platforms[Platform.SLACK].home_channel
        assert hc.name == "ops-alerts"

    def test_thread_id_is_set_when_provided(self, monkeypatch):
        monkeypatch.setenv("SLACK_HOME_CHANNEL", "C0123456789")
        monkeypatch.setenv("SLACK_HOME_CHANNEL_THREAD_ID", "1234567890.123456")
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        cfg = _config_with_slack()
        _apply_env_overrides(cfg)

        hc = cfg.platforms[Platform.SLACK].home_channel
        assert hc.thread_id == "1234567890.123456"

    def test_thread_id_is_none_when_absent(self, monkeypatch):
        monkeypatch.setenv("SLACK_HOME_CHANNEL", "C0123456789")
        monkeypatch.delenv("SLACK_HOME_CHANNEL_THREAD_ID", raising=False)
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        cfg = _config_with_slack()
        _apply_env_overrides(cfg)

        hc = cfg.platforms[Platform.SLACK].home_channel
        assert hc.thread_id is None

    def test_no_home_channel_when_slack_absent_from_platforms(self, monkeypatch):
        """SLACK_HOME_CHANNEL alone must not create a Slack platform entry."""
        monkeypatch.setenv("SLACK_HOME_CHANNEL", "C0123456789")
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        cfg = GatewayConfig()  # no Slack entry
        _apply_env_overrides(cfg)

        assert Platform.SLACK not in cfg.platforms

    def test_no_home_channel_when_env_var_unset(self, monkeypatch):
        monkeypatch.delenv("SLACK_HOME_CHANNEL", raising=False)
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        cfg = _config_with_slack()
        _apply_env_overrides(cfg)

        assert cfg.platforms[Platform.SLACK].home_channel is None


# ---------------------------------------------------------------------------
# HomeChannel dataclass - Slack-specific round-trip
# ---------------------------------------------------------------------------

class TestHomeChannelRoundTrip:

    def _make_slack_home_channel(self, thread_id=None) -> HomeChannel:
        return HomeChannel(
            platform=Platform.SLACK,
            chat_id="C0123456789",
            name="general",
            thread_id=thread_id,
        )

    def test_to_dict_contains_expected_keys(self):
        hc = self._make_slack_home_channel()
        d = hc.to_dict()
        assert d["platform"] == "slack"
        assert d["chat_id"] == "C0123456789"
        assert d["name"] == "general"
        assert "thread_id" not in d  # omitted when None

    def test_to_dict_includes_thread_id_when_set(self):
        hc = self._make_slack_home_channel(thread_id="111.222")
        d = hc.to_dict()
        assert d["thread_id"] == "111.222"

    def test_from_dict_round_trip_without_thread(self):
        hc = self._make_slack_home_channel()
        restored = HomeChannel.from_dict(hc.to_dict())
        assert restored.platform == Platform.SLACK
        assert restored.chat_id == "C0123456789"
        assert restored.name == "general"
        assert restored.thread_id is None

    def test_from_dict_round_trip_with_thread(self):
        hc = self._make_slack_home_channel(thread_id="111.222")
        restored = HomeChannel.from_dict(hc.to_dict())
        assert restored.thread_id == "111.222"

    def test_from_dict_coerces_chat_id_to_str(self):
        d = {"platform": "slack", "chat_id": 9876543210, "name": "Home"}
        hc = HomeChannel.from_dict(d)
        assert isinstance(hc.chat_id, str)
        assert hc.chat_id == "9876543210"

    def test_from_dict_defaults_name_to_home(self):
        d = {"platform": "slack", "chat_id": "C999"}
        hc = HomeChannel.from_dict(d)
        assert hc.name == "Home"


# ---------------------------------------------------------------------------
# GatewayConfig.get_home_channel()
# ---------------------------------------------------------------------------

class TestGetHomeChannel:

    def test_returns_home_channel_for_slack(self):
        cfg = _config_with_slack()
        hc = HomeChannel(
            platform=Platform.SLACK,
            chat_id="C0123456789",
            name="general",
        )
        cfg.platforms[Platform.SLACK].home_channel = hc

        result = cfg.get_home_channel(Platform.SLACK)
        assert result is hc

    def test_returns_none_when_no_home_channel_set(self):
        cfg = _config_with_slack()
        assert cfg.get_home_channel(Platform.SLACK) is None

    def test_returns_none_when_platform_absent(self):
        cfg = GatewayConfig()
        assert cfg.get_home_channel(Platform.SLACK) is None

    def test_does_not_bleed_across_platforms(self):
        cfg = GatewayConfig()
        cfg.platforms[Platform.TELEGRAM] = PlatformConfig(
            enabled=True,
            token="tg-token",
            home_channel=HomeChannel(
                platform=Platform.TELEGRAM,
                chat_id="-100999",
                name="tg-home",
            ),
        )
        cfg.platforms[Platform.SLACK] = _slack_config()
        # Slack has no home channel; Telegram does
        assert cfg.get_home_channel(Platform.SLACK) is None
        assert cfg.get_home_channel(Platform.TELEGRAM) is not None
