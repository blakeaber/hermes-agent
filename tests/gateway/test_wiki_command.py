"""WIKI-SLACK P6-D — live /wiki SlackAdapter handler + registry wiring tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_FIXTURE = Path(__file__).parent / "fixtures" / "entity_page_acme.json"


def _make_adapter(client):
    from gateway.platforms.slack import SlackAdapter

    adapter = object.__new__(SlackAdapter)
    adapter._get_client = lambda channel_id: client  # noqa: SLF001
    return adapter


def _client():
    c = MagicMock()
    c.chat_postMessage = AsyncMock(return_value={"ts": "1.2"})
    c.chat_postEphemeral = AsyncMock(return_value={"ts": "1.3"})
    return c


def _patch_atlas(monkeypatch, page):
    from gateway import atlas_wiki_client

    monkeypatch.setattr(
        atlas_wiki_client, "resolve_entity_iri", lambda name: "urn:atlas:acme"
    )

    async def _fetch(iri):
        return page

    monkeypatch.setattr(atlas_wiki_client, "fetch_entity_page", _fetch)


@pytest.mark.asyncio
async def test_wiki_command_posts_rendered_blocks(monkeypatch):
    page = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    _patch_atlas(monkeypatch, page)
    client = _client()
    adapter = _make_adapter(client)

    await adapter._handle_wiki_command(
        {"text": "Acme Corp", "channel_id": "C1", "user_id": "U1"}
    )

    client.chat_postMessage.assert_called_once()
    kwargs = client.chat_postMessage.call_args[1]
    assert kwargs["channel"] == "C1"
    assert isinstance(kwargs["blocks"], list) and kwargs["blocks"]


@pytest.mark.asyncio
async def test_wiki_command_degraded_posts_graceful_message(monkeypatch):
    _patch_atlas(monkeypatch, {"degraded": True, "reason": "ATLAS_BASE_URL unset"})
    client = _client()
    adapter = _make_adapter(client)

    await adapter._handle_wiki_command(
        {"text": "Acme Corp", "channel_id": "C1", "user_id": "U1"}
    )

    client.chat_postMessage.assert_not_called()
    client.chat_postEphemeral.assert_called_once()
    assert "unreachable" in client.chat_postEphemeral.call_args[1]["text"].lower()


@pytest.mark.asyncio
async def test_wiki_command_not_found_posts_graceful_message(monkeypatch):
    _patch_atlas(monkeypatch, {"not_found": True, "iri": "urn:atlas:acme"})
    client = _client()
    adapter = _make_adapter(client)

    await adapter._handle_wiki_command(
        {"text": "Acme Corp", "channel_id": "C1", "user_id": "U1"}
    )

    client.chat_postMessage.assert_not_called()
    client.chat_postEphemeral.assert_called_once()
    assert "no wiki page" in client.chat_postEphemeral.call_args[1]["text"].lower()


@pytest.mark.asyncio
async def test_wiki_command_empty_entity_posts_usage(monkeypatch):
    client = _client()
    adapter = _make_adapter(client)
    await adapter._handle_wiki_command(
        {"text": "", "channel_id": "C1", "user_id": "U1"}
    )
    client.chat_postMessage.assert_not_called()
    client.chat_postEphemeral.assert_called_once()
    assert "usage" in client.chat_postEphemeral.call_args[1]["text"].lower()


def test_wiki_is_registered_in_slash_registry():
    from hermes_cli.commands import slack_native_slashes

    names = {name for name, _desc, _hint in slack_native_slashes()}
    assert "wiki" in names
