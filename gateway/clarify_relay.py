"""
gateway/clarify_relay.py — Plan 074-C (Hermes side of the clarification relay)

Inbound HTTP ingress that lets the agentic-hub orchestrator ask a human a
clarifying question in Slack and receive the answer back, durably, across the
two Hermes processes (health-server ingress + Socket-Mode gateway).

Direction 1 — orchestrator → Slack (this file's HTTP route)
-----------------------------------------------------------
  POST /clarify/ask
    Authorization: Bearer <HERMES_CLARIFY_BEARER>
    body: {"workflow_id": str, "identifier": str, "thread_ref": str, "question": str}

  On receipt we:
    1. authenticate the bearer (HERMES_CLARIFY_BEARER; open in local/test when unset),
    2. post the question into the Slack thread (thread_ref → channel + thread_ts)
       via a STATELESS chat.postMessage call (needs only SLACK_BOT_TOKEN — works
       from the health-server process which has no live gateway client), and
    3. persist a clarify_pending row keyed by thread_ref so the SEPARATE gateway
       process can correlate the user's reply with this workflow.

Direction 2 — Slack reply → orchestrator
----------------------------------------
  Handled in gateway/platforms/slack.py::_handle_slack_message via the helper
  ``maybe_relay_clarify_reply`` below. On a thread reply whose thread_ref has a
  pending row, we POST the answer back to:

    POST {ORCHESTRATOR_SENSOR_URL}/clarify/reply
      Linear-Signature: <hmac-sha256 hex of the raw body, key=LINEAR_WEBHOOK_SECRET>
      body: {"workflow_id": str, "answer": str, "question": str}

  then delete the pending row and short-circuit (the agent is NOT invoked for a
  clarification answer).

Seams reused
------------
  - Bearer-gated aiohttp ingress on :8080 → gateway/forge_server.py pattern
    (register_*_routes called from gateway/health_server.py::run_server).
  - HMAC ``Linear-Signature`` POST to the orchestrator sensor → exact algorithm
    from tools/plan_lifecycle_tool.py::_sign_body / orchestrator _verify_signature.
  - Stateless chat.postMessage → tools/send_message_tool.py::_send_slack pattern,
    extended here with thread_ts.
  - Neon pool access → hermes_storage.get_backend() singleton (shared by both
    processes), same accessor gateway/forge_server.py::_get_pool uses.

thread_ref format
-----------------
  Authoritative thread anchor. Either "<channel_id>:<thread_ts>" (preferred) or a
  bare "<thread_ts>" in which case HERMES_CLARIFY_DEFAULT_CHANNEL must be set.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env var names
# ---------------------------------------------------------------------------

_CLARIFY_BEARER_ENV = "HERMES_CLARIFY_BEARER"
_SLACK_TOKEN_ENV = "SLACK_BOT_TOKEN"
_DEFAULT_CHANNEL_ENV = "HERMES_CLARIFY_DEFAULT_CHANNEL"
_SENSOR_URL_ENV = "ORCHESTRATOR_SENSOR_URL"
_SIGNING_SECRET_ENV = "LINEAR_WEBHOOK_SECRET"

_SENSOR_URL_DEFAULT = "http://orchestrator-sensor.agentic-stack.internal:8000"


# ---------------------------------------------------------------------------
# Bearer auth (mirrors gateway/forge_server.py::_check_forge_auth)
# ---------------------------------------------------------------------------

def _check_clarify_auth(request: "aiohttp.web.Request") -> Optional["aiohttp.web.Response"]:
    """Return None if auth passes; 401 Response on failure.

    When HERMES_CLARIFY_BEARER is unset (local dev / test) all requests pass —
    the same open-in-dev posture as forge_server / api_server.
    """
    import aiohttp.web as web  # noqa: PLC0415

    expected = os.environ.get(_CLARIFY_BEARER_ENV, "")
    if not expected:
        if os.environ.get("HERMES_MODE", "local") == "saas":
            logger.error(
                "clarify_relay: %s unset while HERMES_MODE=saas — failing CLOSED",
                _CLARIFY_BEARER_ENV,
            )
            return web.json_response(
                {"error": "unauthorized", "detail": "clarify auth not configured"},
                status=503,
            )
        logger.debug("clarify_relay: bearer token not configured — allowing all (local dev)")
        return None

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if hmac.compare_digest(token, expected):
            return None

    return web.json_response(
        {"error": "unauthorized", "detail": "Missing or invalid clarify bearer token"},
        status=401,
    )


# ---------------------------------------------------------------------------
# thread_ref parsing
# ---------------------------------------------------------------------------

def _parse_thread_ref(thread_ref: str) -> Tuple[Optional[str], Optional[str]]:
    """Split a thread_ref into (channel_id, thread_ts).

    "<channel>:<thread_ts>" → (channel, thread_ts)
    "<thread_ts>"           → (HERMES_CLARIFY_DEFAULT_CHANNEL or None, thread_ts)

    Returns (None, None) when thread_ref is blank.
    """
    thread_ref = (thread_ref or "").strip()
    if not thread_ref:
        return None, None
    if ":" in thread_ref:
        channel, _, thread_ts = thread_ref.partition(":")
        channel = channel.strip()
        thread_ts = thread_ts.strip()
        return (channel or None), (thread_ts or None)
    # bare thread_ts — need a default channel
    return os.environ.get(_DEFAULT_CHANNEL_ENV, "").strip() or None, thread_ref


# ---------------------------------------------------------------------------
# Stateless Slack thread post (mirrors tools/send_message_tool.py::_send_slack,
# extended with thread_ts so we land inside the right thread)
# ---------------------------------------------------------------------------

async def _post_to_slack_thread(
    *, token: str, channel: str, thread_ts: str, text: str
) -> dict[str, Any]:
    """POST a message into a Slack thread via chat.postMessage.

    Stateless — needs only the bot token, so it works from the health-server
    process that has no live Socket-Mode client. Returns {"ok": bool, ...}.
    """
    import aiohttp  # noqa: PLC0415

    url = "https://slack.com/api/chat.postMessage"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "channel": channel,
        "text": text,
        "thread_ts": thread_ts,
        "mrkdwn": True,
    }
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, headers=headers, json=payload) as resp:
            return await resp.json()


# ---------------------------------------------------------------------------
# Neon pool accessor (mirrors gateway/forge_server.py::_get_pool)
# ---------------------------------------------------------------------------

async def _get_pool():
    """Return the asyncpg pool from the NeonBackend singleton.

    Raises RuntimeError if the active backend is not NeonBackend (HERMES_MODE=saas).
    """
    from hermes_storage import get_backend  # noqa: PLC0415
    from hermes_storage.neon_backend import NeonBackend  # noqa: PLC0415

    backend = await get_backend()
    if not isinstance(backend, NeonBackend):
        raise RuntimeError(
            "clarify_relay: NeonBackend required (HERMES_MODE=saas); "
            f"got {type(backend).__name__}"
        )
    return backend._require_pool()


async def _store_pending(
    *, thread_ref: str, workflow_id: str, question: str, identifier: Optional[str]
) -> None:
    """Upsert a clarify_pending row (idempotent on thread_ref)."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO clarify_pending (thread_ref, workflow_id, question, identifier)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (thread_ref) DO UPDATE
              SET workflow_id = EXCLUDED.workflow_id,
                  question    = EXCLUDED.question,
                  identifier  = EXCLUDED.identifier,
                  created_at  = now()
            """,
            thread_ref,
            workflow_id,
            question or "",
            identifier,
        )


async def _peek_pending(thread_ref: str) -> Optional[dict[str, Any]]:
    """Fetch (WITHOUT deleting) the pending row for thread_ref. Returns row or None."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT workflow_id, question, identifier "
            "FROM clarify_pending WHERE thread_ref = $1",
            thread_ref,
        )
    if row is None:
        return None
    return {
        "workflow_id": row["workflow_id"],
        "question": row["question"],
        "identifier": row["identifier"],
    }


async def _delete_pending(thread_ref: str) -> None:
    """Delete the pending row once its answer has been durably relayed."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM clarify_pending WHERE thread_ref = $1", thread_ref
        )


# ---------------------------------------------------------------------------
# HMAC sign + POST back to the orchestrator sensor
# (mirrors tools/plan_lifecycle_tool.py::_sign_body / _post_to_sensor)
# ---------------------------------------------------------------------------

def _sign_body(secret: str, raw_body: bytes) -> str:
    """Linear-Signature value: hmac-sha256 hex of raw_body, keyed by *secret*."""
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


async def _post_reply_to_sensor(
    *, workflow_id: str, answer: str, question: str
) -> bool:
    """POST the answer to {ORCHESTRATOR_SENSOR_URL}/clarify/reply, HMAC-signed.

    Returns True on a 2xx. Logs and returns False on any failure (the reply
    relay must never crash the Slack message handler).
    """
    import aiohttp  # noqa: PLC0415

    secret = os.environ.get(_SIGNING_SECRET_ENV, "")
    if not secret:
        logger.error("clarify_relay: %s unset — cannot sign reply", _SIGNING_SECRET_ENV)
        return False

    base = os.environ.get(_SENSOR_URL_ENV, _SENSOR_URL_DEFAULT).rstrip("/")
    url = f"{base}/clarify/reply"
    payload = {"workflow_id": workflow_id, "answer": answer, "question": question}
    raw_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Linear-Signature": _sign_body(secret, raw_body),
    }

    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=raw_body, headers=headers) as resp:
                if 200 <= resp.status < 300:
                    return True
                body = (await resp.text())[:300]
                logger.error(
                    "clarify_relay: sensor /clarify/reply returned %s: %s",
                    resp.status, body,
                )
                return False
    except Exception as exc:  # noqa: BLE001
        logger.error("clarify_relay: POST to sensor /clarify/reply failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Gateway-side reply relay (called from slack.py::_handle_slack_message)
# ---------------------------------------------------------------------------

async def maybe_relay_clarify_reply(
    *, channel_id: str, thread_ts: Optional[str], answer: str
) -> bool:
    """If this thread has a pending clarification, relay the answer and consume it.

    Returns True when the message WAS a clarification answer (caller should
    short-circuit and NOT dispatch to the agent), False otherwise.

    Defensive: any internal error is swallowed (returns False) so a relay
    failure degrades to normal agent handling rather than dropping the message.
    """
    if not channel_id or not thread_ts:
        return False
    answer = (answer or "").strip()
    if not answer:
        return False

    thread_ref = f"{channel_id}:{thread_ts}"
    try:
        pending = await _peek_pending(thread_ref)
    except Exception as exc:  # noqa: BLE001
        logger.debug("clarify_relay: pending lookup failed for %s: %s", thread_ref, exc)
        return False

    if pending is None:
        return False

    ok = await _post_reply_to_sensor(
        workflow_id=pending["workflow_id"],
        answer=answer,
        question=pending.get("question") or "",
    )
    if not ok:
        logger.error(
            "clarify_relay: FAILED to relay answer for workflow=%s thread=%s — "
            "leaving pending row intact for retry",
            pending["workflow_id"], thread_ref,
        )
        return False

    try:
        await _delete_pending(thread_ref)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "clarify_relay: relayed but failed to delete pending row %s: %s",
            thread_ref, exc,
        )
    logger.info(
        "clarify_relay: relayed answer for workflow=%s thread=%s",
        pending["workflow_id"], thread_ref,
    )
    return True


# ---------------------------------------------------------------------------
# Inbound HTTP route: POST /clarify/ask
# ---------------------------------------------------------------------------

async def handle_clarify_ask(request: "aiohttp.web.Request") -> "aiohttp.web.Response":
    """Receive a clarification question from the orchestrator and post it to Slack."""
    import aiohttp.web as web  # noqa: PLC0415

    auth_err = _check_clarify_auth(request)
    if auth_err:
        return auth_err

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "bad_request", "detail": "invalid JSON body"}, status=400)

    workflow_id = str(body.get("workflow_id", "")).strip()
    thread_ref = str(body.get("thread_ref", "")).strip()
    question = str(body.get("question", "")).strip()
    identifier = body.get("identifier")
    identifier = str(identifier).strip() if identifier is not None else None

    missing = [
        k for k, v in (("workflow_id", workflow_id), ("thread_ref", thread_ref), ("question", question))
        if not v
    ]
    if missing:
        return web.json_response(
            {"error": "bad_request", "detail": f"missing required fields: {', '.join(missing)}"},
            status=400,
        )

    channel, thread_ts = _parse_thread_ref(thread_ref)
    if not channel or not thread_ts:
        return web.json_response(
            {
                "error": "bad_request",
                "detail": (
                    "thread_ref must be '<channel_id>:<thread_ts>' (or a bare "
                    "thread_ts with HERMES_CLARIFY_DEFAULT_CHANNEL set)"
                ),
            },
            status=400,
        )

    token = os.environ.get(_SLACK_TOKEN_ENV, "")
    if not token:
        logger.error("clarify_relay: %s not set — cannot post question", _SLACK_TOKEN_ENV)
        return web.json_response(
            {"error": "unconfigured", "detail": f"{_SLACK_TOKEN_ENV} not set"},
            status=503,
        )

    # Post the question into the thread.
    try:
        slack_resp = await _post_to_slack_thread(
            token=token, channel=channel, thread_ts=thread_ts, text=question,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("clarify_relay: chat.postMessage raised: %s", exc)
        return web.json_response(
            {"error": "slack_error", "detail": f"chat.postMessage failed: {exc}"},
            status=502,
        )

    if not slack_resp.get("ok"):
        return web.json_response(
            {"error": "slack_error", "detail": f"slack: {slack_resp.get('error', 'unknown')}"},
            status=502,
        )

    # Persist the mapping AFTER the post succeeds. Normalise the stored
    # thread_ref to the canonical "channel:thread_ts" the gateway reply path
    # reconstructs, so a bare-thread_ts request still correlates.
    canonical_ref = f"{channel}:{thread_ts}"
    try:
        await _store_pending(
            thread_ref=canonical_ref,
            workflow_id=workflow_id,
            question=question,
            identifier=identifier,
        )
    except Exception as exc:  # noqa: BLE001
        # The question is already posted; failing to persist means we can't
        # correlate the reply. Surface it so the orchestrator can retry.
        logger.error("clarify_relay: failed to persist pending row: %s", exc)
        return web.json_response(
            {"error": "persist_failed", "detail": f"could not store pending mapping: {exc}"},
            status=500,
        )

    return web.json_response(
        {"ok": True, "posted_ts": slack_resp.get("ts"), "thread_ref": canonical_ref},
        status=200,
    )


# ---------------------------------------------------------------------------
# Route registration (mirrors gateway/forge_server.py::register_forge_routes)
# ---------------------------------------------------------------------------

def register_clarify_routes(app: "aiohttp.web.Application") -> None:
    """Add /clarify/* routes to an existing aiohttp Application.

    Called from gateway/health_server.py::run_server() so the clarify ingress
    shares the :8080 server (no new port). Pure addition.
    """
    app.router.add_post("/clarify/ask", handle_clarify_ask)
    logger.info("clarify_relay: /clarify/ask route registered on :8080")
