"""
tests/gateway/test_clarify_relay.py — Plan 074-C

Unit tests for gateway/clarify_relay.py — the Hermes side of the orchestrator
clarification relay.

Pattern mirrors tests/gateway/test_forge_server.py: MagicMock aiohttp requests,
AsyncMock pool, and patched _get_pool. No live Neon, Slack, or sensor required.

Inventory
  Auth
    1. test_auth_required_when_token_configured   — 401 when bearer absent
    2. test_auth_passes_with_correct_bearer       — pass with right bearer
    3. test_auth_open_when_no_token_configured    — open in dev (no token)
    4. test_auth_rejects_wrong_bearer             — 401 on wrong token
  thread_ref parsing
    5. test_parse_thread_ref_channel_and_ts       — "C:ts" → (C, ts)
    6. test_parse_thread_ref_bare_uses_default    — bare ts + default channel env
    7. test_parse_thread_ref_bare_no_default      — bare ts, no default → (None, ts)
  HMAC signing
    8. test_sign_body_matches_orchestrator_algo   — exact hmac-sha256 hex
  /clarify/ask
    9. test_ask_missing_fields_400
    10. test_ask_bad_thread_ref_400
    11. test_ask_no_slack_token_503
    12. test_ask_happy_path_posts_and_persists
    13. test_ask_slack_error_502
  reply relay
    14. test_relay_no_pending_returns_false
    15. test_relay_pending_posts_back_and_consumes
    16. test_relay_blank_answer_false
  route registration
    17. test_register_clarify_routes
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pool(fetchrow_result=None):
    """Mock asyncpg pool. conn.execute / conn.fetchrow are AsyncMocks."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value="DELETE 1")
    conn.fetchrow = AsyncMock(return_value=fetchrow_result)

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=acquire_cm)
    return pool, conn


@pytest.fixture()
def clear_bearer(monkeypatch):
    monkeypatch.delenv("HERMES_CLARIFY_BEARER", raising=False)


@pytest.fixture()
def set_bearer(monkeypatch):
    monkeypatch.setenv("HERMES_CLARIFY_BEARER", "clarify-secret")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestClarifyAuth:
    def test_auth_required_when_token_configured(self, set_bearer):
        from gateway.clarify_relay import _check_clarify_auth
        req = MagicMock()
        req.headers = {}
        result = _check_clarify_auth(req)
        assert result is not None and result.status == 401

    def test_auth_passes_with_correct_bearer(self, set_bearer):
        from gateway.clarify_relay import _check_clarify_auth
        req = MagicMock()
        req.headers = {"Authorization": "Bearer clarify-secret"}
        assert _check_clarify_auth(req) is None

    def test_auth_open_when_no_token_configured(self, clear_bearer):
        from gateway.clarify_relay import _check_clarify_auth
        req = MagicMock()
        req.headers = {}
        assert _check_clarify_auth(req) is None

    def test_auth_rejects_wrong_bearer(self, set_bearer):
        from gateway.clarify_relay import _check_clarify_auth
        req = MagicMock()
        req.headers = {"Authorization": "Bearer nope"}
        result = _check_clarify_auth(req)
        assert result is not None and result.status == 401


# ---------------------------------------------------------------------------
# thread_ref parsing
# ---------------------------------------------------------------------------

class TestParseThreadRef:
    def test_parse_thread_ref_channel_and_ts(self, monkeypatch):
        from gateway.clarify_relay import _parse_thread_ref
        monkeypatch.delenv("HERMES_CLARIFY_DEFAULT_CHANNEL", raising=False)
        assert _parse_thread_ref("C123:1700000000.000100") == ("C123", "1700000000.000100")

    def test_parse_thread_ref_bare_uses_default(self, monkeypatch):
        from gateway.clarify_relay import _parse_thread_ref
        monkeypatch.setenv("HERMES_CLARIFY_DEFAULT_CHANNEL", "CDEFAULT")
        assert _parse_thread_ref("1700000000.000100") == ("CDEFAULT", "1700000000.000100")

    def test_parse_thread_ref_bare_no_default(self, monkeypatch):
        from gateway.clarify_relay import _parse_thread_ref
        monkeypatch.delenv("HERMES_CLARIFY_DEFAULT_CHANNEL", raising=False)
        assert _parse_thread_ref("1700000000.000100") == (None, "1700000000.000100")


# ---------------------------------------------------------------------------
# HMAC signing — must match orchestrator _verify_signature exactly
# ---------------------------------------------------------------------------

class TestSignBody:
    def test_sign_body_matches_orchestrator_algo(self):
        from gateway.clarify_relay import _sign_body
        secret = "shared-webhook-secret"
        body = json.dumps({"a": 1}, ensure_ascii=False).encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        assert _sign_body(secret, body) == expected


# ---------------------------------------------------------------------------
# POST /clarify/ask
# ---------------------------------------------------------------------------

class TestClarifyAsk:
    @pytest.mark.asyncio
    async def test_ask_missing_fields_400(self, clear_bearer):
        from gateway.clarify_relay import handle_clarify_ask
        req = MagicMock()
        req.headers = {}
        req.json = AsyncMock(return_value={"workflow_id": "wf-1"})  # missing thread_ref/question
        resp = await handle_clarify_ask(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_ask_bad_thread_ref_400(self, clear_bearer, monkeypatch):
        from gateway.clarify_relay import handle_clarify_ask
        monkeypatch.delenv("HERMES_CLARIFY_DEFAULT_CHANNEL", raising=False)
        req = MagicMock()
        req.headers = {}
        # bare thread_ts, no default channel → cannot resolve a channel
        req.json = AsyncMock(return_value={
            "workflow_id": "wf-1", "thread_ref": "1700.0001", "question": "Which repo?",
        })
        resp = await handle_clarify_ask(req)
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_ask_no_slack_token_503(self, clear_bearer, monkeypatch):
        from gateway.clarify_relay import handle_clarify_ask
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
        req = MagicMock()
        req.headers = {}
        req.json = AsyncMock(return_value={
            "workflow_id": "wf-1", "thread_ref": "C1:1700.0001", "question": "Which repo?",
        })
        resp = await handle_clarify_ask(req)
        assert resp.status == 503

    @pytest.mark.asyncio
    async def test_ask_happy_path_posts_and_persists(self, clear_bearer, monkeypatch):
        from gateway.clarify_relay import handle_clarify_ask
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        pool, conn = _make_pool()

        req = MagicMock()
        req.headers = {}
        req.json = AsyncMock(return_value={
            "workflow_id": "wf-42",
            "identifier": "AGE-579",
            "thread_ref": "C1:1700.0001",
            "question": "Which repo should I target?",
        })

        with patch("gateway.clarify_relay._post_to_slack_thread",
                   new=AsyncMock(return_value={"ok": True, "ts": "1700.0002"})) as post_mock, \
             patch("gateway.clarify_relay._get_pool", new=AsyncMock(return_value=pool)):
            resp = await handle_clarify_ask(req)

        assert resp.status == 200
        data = json.loads(resp.text)
        assert data["ok"] is True
        assert data["thread_ref"] == "C1:1700.0001"
        # posted into the right thread
        kwargs = post_mock.call_args.kwargs
        assert kwargs["channel"] == "C1"
        assert kwargs["thread_ts"] == "1700.0001"
        assert kwargs["text"] == "Which repo should I target?"
        # persisted an upsert
        assert conn.execute.await_count == 1
        sql = conn.execute.await_args.args[0]
        assert "INSERT INTO clarify_pending" in sql
        assert conn.execute.await_args.args[1] == "C1:1700.0001"  # thread_ref
        assert conn.execute.await_args.args[2] == "wf-42"          # workflow_id

    @pytest.mark.asyncio
    async def test_ask_slack_error_502(self, clear_bearer, monkeypatch):
        from gateway.clarify_relay import handle_clarify_ask
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
        req = MagicMock()
        req.headers = {}
        req.json = AsyncMock(return_value={
            "workflow_id": "wf-1", "thread_ref": "C1:1700.0001", "question": "Q?",
        })
        with patch("gateway.clarify_relay._post_to_slack_thread",
                   new=AsyncMock(return_value={"ok": False, "error": "channel_not_found"})):
            resp = await handle_clarify_ask(req)
        assert resp.status == 502


# ---------------------------------------------------------------------------
# Reply relay (gateway-side)
# ---------------------------------------------------------------------------

class TestReplyRelay:
    @pytest.mark.asyncio
    async def test_relay_no_pending_returns_false(self):
        from gateway.clarify_relay import maybe_relay_clarify_reply
        pool, conn = _make_pool(fetchrow_result=None)  # DELETE RETURNING → no row
        with patch("gateway.clarify_relay._get_pool", new=AsyncMock(return_value=pool)):
            relayed = await maybe_relay_clarify_reply(
                channel_id="C1", thread_ts="1700.0001", answer="blakeaber/agentic-hub",
            )
        assert relayed is False

    @pytest.mark.asyncio
    async def test_relay_pending_posts_back_and_consumes(self, monkeypatch):
        from gateway.clarify_relay import maybe_relay_clarify_reply
        monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", "shared-secret")
        monkeypatch.setenv("ORCHESTRATOR_SENSOR_URL", "http://sensor:8000")

        row = {"workflow_id": "wf-42", "question": "Which repo?", "identifier": "AGE-579"}
        pool, conn = _make_pool(fetchrow_result=row)

        with patch("gateway.clarify_relay._get_pool", new=AsyncMock(return_value=pool)), \
             patch("gateway.clarify_relay._post_reply_to_sensor",
                   new=AsyncMock(return_value=True)) as sensor_mock:
            relayed = await maybe_relay_clarify_reply(
                channel_id="C1", thread_ts="1700.0001", answer="  blakeaber/agentic-hub  ",
            )

        assert relayed is True
        # DELETE ... RETURNING consumed the row
        sql = conn.fetchrow.await_args.args[0]
        assert "DELETE FROM clarify_pending" in sql
        assert conn.fetchrow.await_args.args[1] == "C1:1700.0001"
        # answer posted back, trimmed, with the echoed question
        kwargs = sensor_mock.call_args.kwargs
        assert kwargs["workflow_id"] == "wf-42"
        assert kwargs["answer"] == "blakeaber/agentic-hub"
        assert kwargs["question"] == "Which repo?"

    @pytest.mark.asyncio
    async def test_relay_blank_answer_false(self):
        from gateway.clarify_relay import maybe_relay_clarify_reply
        # blank answer never touches the DB
        with patch("gateway.clarify_relay._get_pool",
                   new=AsyncMock(side_effect=AssertionError("should not be called"))):
            relayed = await maybe_relay_clarify_reply(
                channel_id="C1", thread_ts="1700.0001", answer="   ",
            )
        assert relayed is False


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

class TestRegisterRoutes:
    def test_register_clarify_routes(self):
        import aiohttp.web as web
        from gateway.clarify_relay import register_clarify_routes

        app = web.Application()
        register_clarify_routes(app)
        paths = {r.resource.canonical for r in app.router.routes()}
        assert "/clarify/ask" in paths
