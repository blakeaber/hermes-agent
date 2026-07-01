"""WIKI-SLACK P6-B — Atlas wiki client + slug resolver tests (aiohttp mocked)."""

from __future__ import annotations

import aiohttp
import pytest

from gateway import atlas_wiki_client as awc

# Cross-repo slug contract golden pairs — these MUST match army-of-one
# core/ids.org_iri(name). A slugify change in either repo breaks these.
SLUG_GOLDEN = [
    ("Acme Corp", "https://atlas.blakeaber.dev/org/acme-corp"),
    ("Thoma Bravo", "https://atlas.blakeaber.dev/org/thoma-bravo"),
    ("A.B.C  Ventures!!", "https://atlas.blakeaber.dev/org/a-b-c-ventures"),
    ("Café Déjà Co", "https://atlas.blakeaber.dev/org/cafe-deja-co"),
]


@pytest.mark.parametrize("name,expected", SLUG_GOLDEN)
def test_resolve_entity_iri_matches_army_of_one_slug(name, expected):
    assert awc.resolve_entity_iri(name) == expected


# ---- fail-soft aiohttp mocking ---------------------------------------------


class _FakeResp:
    def __init__(self, status: int, payload: dict | None = None) -> None:
        self.status = status
        self._payload = payload or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, resp: _FakeResp | Exception) -> None:
        self._resp = resp
        self.last_url = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def get(self, url, headers=None):  # noqa: ANN001
        self.last_url = url
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


def _install_session(monkeypatch, resp):
    session_holder = [None]

    def create_session(*a, **k):
        session = _FakeSession(resp)
        session_holder[0] = session
        return session

    monkeypatch.setattr(aiohttp, "ClientSession", create_session)
    return session_holder


@pytest.mark.asyncio
async def test_fetch_returns_page_on_200(monkeypatch):
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.local:8000")
    page = {"iri": "urn:x", "title": "X", "markdown": "x [cite:c1].", "citations": []}
    _ = _install_session(monkeypatch, _FakeResp(200, page))
    result = await awc.fetch_entity_page("urn:x")
    assert result["title"] == "X"


@pytest.mark.asyncio
async def test_fetch_404_returns_not_found(monkeypatch):
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.local:8000")
    _install_session(monkeypatch, _FakeResp(404))
    result = await awc.fetch_entity_page("urn:missing")
    assert result == {"not_found": True, "iri": "urn:missing"}


@pytest.mark.asyncio
async def test_fetch_5xx_returns_degraded_never_raises(monkeypatch):
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.local:8000")
    _install_session(monkeypatch, _FakeResp(503))
    result = await awc.fetch_entity_page("urn:x")
    assert result["degraded"] is True


@pytest.mark.asyncio
async def test_fetch_timeout_returns_degraded_never_raises(monkeypatch):
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.local:8000")
    _install_session(monkeypatch, TimeoutError("timed out"))
    result = await awc.fetch_entity_page("urn:x")
    assert result["degraded"] is True


@pytest.mark.asyncio
async def test_fetch_unset_base_url_returns_degraded(monkeypatch):
    monkeypatch.delenv("ATLAS_BASE_URL", raising=False)
    result = await awc.fetch_entity_page("urn:x")
    assert result["degraded"] is True
    assert "ATLAS_BASE_URL" in result["reason"]


@pytest.mark.asyncio
async def test_fetch_prefers_read_base_url_when_set(monkeypatch):
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.local:8000")
    monkeypatch.setenv("ATLAS_READ_BASE_URL", "http://atlas-read.local:8001")
    page = {"iri": "urn:x", "title": "X", "markdown": "x [cite:c1].", "citations": []}
    session_holder = _install_session(monkeypatch, _FakeResp(200, page))
    result = await awc.fetch_entity_page("urn:x")
    assert result["title"] == "X"
    assert session_holder[0].last_url.startswith("http://atlas-read.local:8001")


@pytest.mark.asyncio
async def test_fetch_falls_back_to_base_url_when_read_url_unset(monkeypatch):
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.local:8000")
    monkeypatch.delenv("ATLAS_READ_BASE_URL", raising=False)
    page = {"iri": "urn:x", "title": "X", "markdown": "x [cite:c1].", "citations": []}
    session_holder = _install_session(monkeypatch, _FakeResp(200, page))
    result = await awc.fetch_entity_page("urn:x")
    assert result["title"] == "X"
    assert session_holder[0].last_url.startswith("http://atlas.local:8000")
