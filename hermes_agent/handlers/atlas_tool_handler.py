"""
atlas_tool_handler.py
---------------------
Gateway-layer handler for the ``atlas_recall`` tool (AGE-469-D).

Wraps the low-level ``atlas_recall`` implementation from ``gateway.run``
with an explicit configuration-validation gate so that calls made when the
Atlas plugin is misconfigured fail fast with a clear error instead of
silently returning empty results.

Design contract
~~~~~~~~~~~~~~~
* ``AtlasToolHandler`` is the single public surface.  Callers instantiate it
  with an ``AtlasPluginConfig`` (or let it build one from the environment via
  ``AtlasToolHandler.from_env()``) and then call ``recall()``.
* ``recall()`` raises ``AtlasConfigError`` when the config is invalid,
  propagating the same exception type that ``AtlasPluginConfig.validate()``
  raises so callers have a single exception to handle.
* The underlying network call is delegated to ``gateway.run.atlas_recall``
  which already handles ``ImportError`` (plugin not installed) and generic
  exceptions, returning a JSON-encoded error string in those cases.
"""

from __future__ import annotations

from typing import Optional

from plugins.memory.atlas_contract import AtlasConfigError, AtlasPluginConfig


class AtlasToolHandler:
    """Validates Atlas plugin configuration then delegates to ``atlas_recall``.

    Parameters
    ----------
    config:
        A pre-built :class:`~plugins.memory.atlas_contract.AtlasPluginConfig`
        instance.  When *None* the handler is constructed without a config and
        every call to :meth:`recall` will raise :class:`AtlasConfigError`.
    """

    def __init__(self, config: Optional[AtlasPluginConfig] = None) -> None:
        self._config: Optional[AtlasPluginConfig] = config

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "AtlasToolHandler":
        """Build a handler whose config is read from environment variables.

        Delegates to :meth:`AtlasPluginConfig.from_env` so the same
        environment-variable names (``ATLAS_API_URL``, ``ATLAS_API_KEY``,
        ``ATLAS_PLUGIN_ENABLED``) are honoured.
        """
        return cls(config=AtlasPluginConfig.from_env())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recall(self, query: str, *, top_k: int = 5) -> str:
        """Retrieve relevant passages from the Atlas knowledge base.

        Parameters
        ----------
        query:
            Natural-language search query.
        top_k:
            Maximum number of passages to return (default 5).

        Returns
        -------
        str
            JSON-encoded list of passage dicts, each with keys
            ``{"id", "text", "score"}``.  Returns a JSON error string on
            failure (mirrors the behaviour of the underlying
            ``gateway.run.atlas_recall`` implementation).

        Raises
        ------
        AtlasConfigError
            When the handler's :class:`AtlasPluginConfig` is invalid or
            missing.  This is raised *before* any network call is made so
            callers can distinguish configuration problems from transient
            network failures.
        """
        self._validate()
        # Delegate to the gateway-level implementation which handles the
        # actual HTTP call and wraps all exceptions in a JSON error string.
        from gateway.run import atlas_recall as _atlas_recall

        return _atlas_recall(query, top_k=top_k)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        """Raise ``AtlasConfigError`` when the config is absent or invalid."""
        if self._config is None:
            raise AtlasConfigError(
                "Atlas plugin configuration is invalid:\n"
                "  • No AtlasPluginConfig was provided to AtlasToolHandler."
            )
        self._config.validate()
