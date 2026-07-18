"""
atlas_contract.py
-----------------
Typed configuration contract for the Atlas plugin (AGE-469).

Root-cause findings (tests/atlas_plugin/findings_age469.md) identified three
config keys that must be present and correctly set before the plugin is allowed
to initialise:

    ATLAS_API_URL        - Base URL of the Atlas REST API  (required)
    ATLAS_API_KEY        - Authentication token            (required)
    ATLAS_PLUGIN_ENABLED - Feature flag                   (must be True)

When any of these invariants is violated the plugin previously entered a silent
no-op state.  This module makes the contract explicit: callers must call
``AtlasPluginConfig.validate()`` at startup and handle the raised exception
rather than silently continuing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


class AtlasConfigError(ValueError):
    """Raised when the Atlas plugin configuration is incomplete or disabled."""


@dataclass
class AtlasPluginConfig:
    """Holds and validates the runtime configuration for the Atlas plugin.

    Parameters
    ----------
    atlas_api_url:
        Base URL of the Atlas REST API.  Required - no default.
    atlas_api_key:
        Authentication token for the Atlas API.  Required - no default.
    atlas_plugin_enabled:
        Feature flag.  Must be ``True`` for the plugin to operate.
        Defaults to ``False`` (safe/disabled) matching the production default
        that caused AGE-469.
    """

    atlas_api_url: Optional[str] = field(default=None)
    atlas_api_key: Optional[str] = field(default=None)
    atlas_plugin_enabled: bool = field(default=False)

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "AtlasPluginConfig":
        """Build a config instance from environment variables.

        Reads:
            ``ATLAS_API_URL``        → :attr:`atlas_api_url`
            ``ATLAS_API_KEY``        → :attr:`atlas_api_key`
            ``ATLAS_PLUGIN_ENABLED`` → :attr:`atlas_plugin_enabled`
                                       (``"true"`` / ``"1"`` / ``"yes"``
                                        are treated as *True*; anything else
                                        is *False*)
        """
        raw_enabled = os.environ.get("ATLAS_PLUGIN_ENABLED", "false").strip().lower()
        enabled = raw_enabled in {"true", "1", "yes"}
        return cls(
            atlas_api_url=os.environ.get("ATLAS_API_URL") or None,
            atlas_api_key=os.environ.get("ATLAS_API_KEY") or None,
            atlas_plugin_enabled=enabled,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Assert that the configuration is complete and the plugin is enabled.

        Raises
        ------
        AtlasConfigError
            If ``ATLAS_PLUGIN_ENABLED`` is ``False``, or if either
            ``ATLAS_API_URL`` or ``ATLAS_API_KEY`` is absent/empty.

        Notes
        -----
        This method is intentionally strict: it is better to fail fast at
        startup with a clear error than to silently skip scan cycles (the
        behaviour that caused AGE-469).
        """
        errors: list[str] = []

        if not self.atlas_plugin_enabled:
            errors.append(
                "ATLAS_PLUGIN_ENABLED is False – set it to True to activate the plugin."
            )

        if not self.atlas_api_url:
            errors.append("ATLAS_API_URL is missing or empty.")

        if not self.atlas_api_key:
            errors.append("ATLAS_API_KEY is missing or empty.")

        if errors:
            raise AtlasConfigError(
                "Atlas plugin configuration is invalid:\n"
                + "\n".join(f"  • {e}" for e in errors)
            )

    @property
    def is_valid(self) -> bool:
        """Return ``True`` if :meth:`validate` would pass, ``False`` otherwise."""
        try:
            self.validate()
            return True
        except AtlasConfigError:
            return False
