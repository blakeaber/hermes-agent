"""
Tests for hermes_agent.user_identity
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from hermes_agent.user_identity import (
    UserIdentity,
    _DEFAULT_EMAIL,
    _DEFAULT_NAME,
    _env_email,
    _env_name,
    _git_config,
    _git_email,
    _git_name,
    resolve_user_identity,
)


# ---------------------------------------------------------------------------
# UserIdentity dataclass
# ---------------------------------------------------------------------------


class TestUserIdentityDataclass:
    def test_fields_are_accessible(self):
        uid = UserIdentity(name="Alice", email="alice@example.com")
        assert uid.name == "Alice"
        assert uid.email == "alice@example.com"

    def test_is_frozen(self):
        uid = UserIdentity(name="Alice", email="alice@example.com")
        with pytest.raises((AttributeError, TypeError)):
            uid.name = "Bob"  # type: ignore[misc]

    def test_equality(self):
        a = UserIdentity(name="Alice", email="alice@example.com")
        b = UserIdentity(name="Alice", email="alice@example.com")
        assert a == b

    def test_inequality(self):
        a = UserIdentity(name="Alice", email="alice@example.com")
        b = UserIdentity(name="Bob", email="bob@example.com")
        assert a != b


# ---------------------------------------------------------------------------
# Environment-variable helpers
# ---------------------------------------------------------------------------


class TestEnvHelpers:
    def test_env_name_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("HERMES_USER_NAME", "EnvUser")
        assert _env_name() == "EnvUser"

    def test_env_name_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("HERMES_USER_NAME", raising=False)
        assert _env_name() is None

    def test_env_name_returns_none_for_empty_string(self, monkeypatch):
        monkeypatch.setenv("HERMES_USER_NAME", "")
        assert _env_name() is None

    def test_env_email_returns_value_when_set(self, monkeypatch):
        monkeypatch.setenv("HERMES_USER_EMAIL", "env@example.com")
        assert _env_email() == "env@example.com"

    def test_env_email_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv("HERMES_USER_EMAIL", raising=False)
        assert _env_email() is None

    def test_env_email_returns_none_for_empty_string(self, monkeypatch):
        monkeypatch.setenv("HERMES_USER_EMAIL", "")
        assert _env_email() is None


# ---------------------------------------------------------------------------
# Git-config helper
# ---------------------------------------------------------------------------


class TestGitConfig:
    def _make_completed_process(self, stdout: bytes, returncode: int = 0):
        mock = MagicMock(spec=subprocess.CompletedProcess)
        mock.returncode = returncode
        mock.stdout = stdout
        return mock

    def test_returns_value_on_success(self):
        with patch("hermes_agent.user_identity.subprocess.run") as mock_run:
            mock_run.return_value = self._make_completed_process(b"Alice\n")
            result = _git_config("user.name")
        assert result == "Alice"

    def test_returns_none_on_nonzero_exit(self):
        with patch("hermes_agent.user_identity.subprocess.run") as mock_run:
            mock_run.return_value = self._make_completed_process(b"", returncode=1)
            result = _git_config("user.name")
        assert result is None

    def test_returns_none_when_git_not_found(self):
        with patch(
            "hermes_agent.user_identity.subprocess.run",
            side_effect=FileNotFoundError,
        ):
            result = _git_config("user.name")
        assert result is None

    def test_returns_none_on_timeout(self):
        with patch(
            "hermes_agent.user_identity.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5),
        ):
            result = _git_config("user.name")
        assert result is None

    def test_returns_none_for_empty_output(self):
        with patch("hermes_agent.user_identity.subprocess.run") as mock_run:
            mock_run.return_value = self._make_completed_process(b"   \n")
            result = _git_config("user.name")
        assert result is None

    def test_strips_whitespace(self):
        with patch("hermes_agent.user_identity.subprocess.run") as mock_run:
            mock_run.return_value = self._make_completed_process(b"  Bob  \n")
            result = _git_config("user.name")
        assert result == "Bob"

    def test_git_name_calls_correct_key(self):
        with patch("hermes_agent.user_identity._git_config") as mock_gc:
            mock_gc.return_value = "GitUser"
            assert _git_name() == "GitUser"
            mock_gc.assert_called_once_with("user.name")

    def test_git_email_calls_correct_key(self):
        with patch("hermes_agent.user_identity._git_config") as mock_gc:
            mock_gc.return_value = "git@example.com"
            assert _git_email() == "git@example.com"
            mock_gc.assert_called_once_with("user.email")


# ---------------------------------------------------------------------------
# resolve_user_identity - priority ordering
# ---------------------------------------------------------------------------


class TestResolveUserIdentity:
    # -- name resolution --

    def test_env_name_takes_priority_over_git_and_default(self, monkeypatch):
        monkeypatch.setenv("HERMES_USER_NAME", "EnvName")
        monkeypatch.setenv("HERMES_USER_EMAIL", "env@example.com")
        with patch("hermes_agent.user_identity._git_name", return_value="GitName"):
            uid = resolve_user_identity()
        assert uid.name == "EnvName"

    def test_git_name_used_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("HERMES_USER_NAME", raising=False)
        monkeypatch.setenv("HERMES_USER_EMAIL", "env@example.com")
        with patch("hermes_agent.user_identity._git_name", return_value="GitName"):
            uid = resolve_user_identity()
        assert uid.name == "GitName"

    def test_default_name_used_when_env_and_git_absent(self, monkeypatch):
        monkeypatch.delenv("HERMES_USER_NAME", raising=False)
        monkeypatch.setenv("HERMES_USER_EMAIL", "env@example.com")
        with patch("hermes_agent.user_identity._git_name", return_value=None):
            uid = resolve_user_identity()
        assert uid.name == _DEFAULT_NAME

    # -- email resolution --

    def test_env_email_takes_priority_over_git_and_default(self, monkeypatch):
        monkeypatch.setenv("HERMES_USER_NAME", "EnvName")
        monkeypatch.setenv("HERMES_USER_EMAIL", "env@example.com")
        with patch("hermes_agent.user_identity._git_email", return_value="git@example.com"):
            uid = resolve_user_identity()
        assert uid.email == "env@example.com"

    def test_git_email_used_when_env_absent(self, monkeypatch):
        monkeypatch.setenv("HERMES_USER_NAME", "EnvName")
        monkeypatch.delenv("HERMES_USER_EMAIL", raising=False)
        with patch("hermes_agent.user_identity._git_email", return_value="git@example.com"):
            uid = resolve_user_identity()
        assert uid.email == "git@example.com"

    def test_default_email_used_when_env_and_git_absent(self, monkeypatch):
        monkeypatch.setenv("HERMES_USER_NAME", "EnvName")
        monkeypatch.delenv("HERMES_USER_EMAIL", raising=False)
        with patch("hermes_agent.user_identity._git_email", return_value=None):
            uid = resolve_user_identity()
        assert uid.email == _DEFAULT_EMAIL

    # -- combined / return type --

    def test_returns_user_identity_instance(self, monkeypatch):
        monkeypatch.setenv("HERMES_USER_NAME", "Someone")
        monkeypatch.setenv("HERMES_USER_EMAIL", "someone@example.com")
        uid = resolve_user_identity()
        assert isinstance(uid, UserIdentity)

    def test_full_fallback_to_defaults(self, monkeypatch):
        monkeypatch.delenv("HERMES_USER_NAME", raising=False)
        monkeypatch.delenv("HERMES_USER_EMAIL", raising=False)
        with (
            patch("hermes_agent.user_identity._git_name", return_value=None),
            patch("hermes_agent.user_identity._git_email", return_value=None),
        ):
            uid = resolve_user_identity()
        assert uid.name == _DEFAULT_NAME
        assert uid.email == _DEFAULT_EMAIL

    def test_name_and_email_resolved_independently(self, monkeypatch):
        """Name from env, email from git - each field uses its own priority chain."""
        monkeypatch.setenv("HERMES_USER_NAME", "EnvName")
        monkeypatch.delenv("HERMES_USER_EMAIL", raising=False)
        with (
            patch("hermes_agent.user_identity._git_name", return_value="GitName"),
            patch("hermes_agent.user_identity._git_email", return_value="git@example.com"),
        ):
            uid = resolve_user_identity()
        assert uid.name == "EnvName"
        assert uid.email == "git@example.com"
