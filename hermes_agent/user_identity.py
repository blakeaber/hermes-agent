"""
User identity resolution for Hermes Agent.

Resolves the current user's name and email by consulting multiple sources
in priority order:
  1. Environment variables (HERMES_USER_NAME / HERMES_USER_EMAIL)
  2. Git config (user.name / user.email via `git config --get`)
  3. Hard-coded fallback defaults
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Optional


_DEFAULT_NAME = "Hermes User"
_DEFAULT_EMAIL = "hermes@localhost"


@dataclass(frozen=True)
class UserIdentity:
    """Immutable value object representing a resolved user identity."""

    name: str
    email: str

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} <{self.email}>"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _env_name() -> Optional[str]:
    """Return HERMES_USER_NAME from the environment, or None."""
    return os.environ.get("HERMES_USER_NAME") or None


def _env_email() -> Optional[str]:
    """Return HERMES_USER_EMAIL from the environment, or None."""
    return os.environ.get("HERMES_USER_EMAIL") or None


def _git_config(key: str) -> Optional[str]:
    """
    Query a single git-config key via subprocess.

    Returns the stripped value on success, or None if the key is unset or
    git is not available.
    """
    try:
        result = subprocess.run(
            ["git", "config", "--get", key],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if result.returncode == 0:
            value = result.stdout.decode("utf-8", errors="replace").strip()
            return value if value else None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _git_name() -> Optional[str]:
    return _git_config("user.name")


def _git_email() -> Optional[str]:
    return _git_config("user.email")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_user_identity() -> UserIdentity:
    """
    Resolve the current user's identity.

    Sources are consulted in this priority order for *each* field
    independently:
      1. Environment variable  (HERMES_USER_NAME / HERMES_USER_EMAIL)
      2. Git config            (user.name / user.email)
      3. Built-in default      ("Hermes User" / "hermes@localhost")

    Returns
    -------
    UserIdentity
        A frozen dataclass with ``name`` and ``email`` attributes.
    """
    name: str = (
        _env_name()
        or _git_name()
        or _DEFAULT_NAME
    )
    email: str = (
        _env_email()
        or _git_email()
        or _DEFAULT_EMAIL
    )
    return UserIdentity(name=name, email=email)
