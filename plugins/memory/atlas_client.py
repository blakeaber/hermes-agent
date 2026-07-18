"""
atlas_client.py
---------------
HTTP client for the Atlas REST API (AGE-469).

This module provides ``AtlasClient``, a thin wrapper around ``urllib.request``
that authenticates with the Atlas API using the credentials held in an
``AtlasPluginConfig`` instance.

Design goals
~~~~~~~~~~~~
* **Fail fast** - the constructor calls ``config.validate()`` so a
  misconfigured client is never silently constructed.
* **No third-party dependencies** - uses only the standard library so the
  plugin can be imported in any environment without extra packages.
* **Testable** - the internal ``_request`` method can be monkey-patched in
  tests to avoid real network calls.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional
from urllib.parse import urljoin

from plugins.memory.atlas_contract import AtlasConfigError, AtlasPluginConfig


class AtlasClientError(RuntimeError):
    """Raised when the Atlas API returns an error or is unreachable."""


class AtlasClient:
    """Authenticated HTTP client for the Atlas REST API.

    Parameters
    ----------
    config:
        A fully-populated and *valid* ``AtlasPluginConfig``.  The constructor
        calls :meth:`~AtlasPluginConfig.validate` and raises
        :class:`~plugins.memory.atlas_contract.AtlasConfigError` if the config
        is incomplete or the plugin is disabled.

    Raises
    ------
    AtlasConfigError
        If ``config.validate()`` fails (missing keys, plugin disabled, etc.).
    """

    def __init__(self, config: AtlasPluginConfig) -> None:
        config.validate()  # raises AtlasConfigError if invalid
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_findings(self, path: str = "/findings") -> list[dict[str, Any]]:
        """Fetch findings from the Atlas API.

        Parameters
        ----------
        path:
            URL path relative to ``ATLAS_API_URL``.  Defaults to
            ``"/findings"``.

        Returns
        -------
        list[dict]
            Parsed JSON response body (expected to be a JSON array).

        Raises
        ------
        AtlasClientError
            On any HTTP error or network failure.
        """
        url = self._build_url(path)
        headers = self._auth_headers()
        response_body = self._request(url, headers)
        try:
            return json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise AtlasClientError(
                f"Atlas API returned non-JSON response: {exc}"
            ) from exc

    def health_check(self) -> bool:
        """Return ``True`` if the Atlas API is reachable and responds with 2xx.

        This is a lightweight probe intended for startup health-checks
        (see findings_age469.md - Recommended Fix Path, step 5).

        Returns
        -------
        bool
            ``True`` on success, ``False`` if the API is unreachable or
            returns a non-2xx status.
        """
        try:
            self._request(self._build_url("/health"), self._auth_headers())
            return True
        except AtlasClientError:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_url(self, path: str) -> str:
        """Combine the base URL from config with *path*."""
        base = self._config.atlas_api_url or ""
        # Ensure base ends with "/" so urljoin works predictably
        if not base.endswith("/"):
            base = base + "/"
        # Strip leading "/" from path to avoid double-slash
        return urljoin(base, path.lstrip("/"))

    def _auth_headers(self) -> dict[str, str]:
        """Return the HTTP headers required for authentication."""
        return {
            "Authorization": f"Bearer {self._config.atlas_api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, url: str, headers: dict[str, str]) -> str:
        """Perform a GET request and return the response body as a string.

        This method is intentionally kept simple so tests can patch it.

        Parameters
        ----------
        url:
            Fully-qualified URL to GET.
        headers:
            HTTP headers to include in the request.

        Raises
        ------
        AtlasClientError
            On ``urllib.error.URLError`` (network failure) or
            ``urllib.error.HTTPError`` (non-2xx response).
        """
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req) as resp:  # noqa: S310
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise AtlasClientError(
                f"Atlas API HTTP error {exc.code} for {url}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise AtlasClientError(
                f"Atlas API unreachable at {url}: {exc.reason}"
            ) from exc
