"""Plan 008-C: shadow-mode observability for built-in memory + session_search.

Writes structured JSON-per-line events to ``~/.hermes/logs/memory-shadow.log``
so we can compare what the built-in memory layer captures vs what Atlas
captures vs what session_search returns. Diagnostic only — no enforcement.

The log is intentionally separate from ``agent.log`` so it stays grepable +
parseable without competing for line budget with the main agent stream.

Schema:
  {
    "ts": "<iso-8601 UTC>",
    "event": "memory.write" | "memory.read.snapshot" | "session_search.query",
    "action": "add" | "replace" | "remove" | null,
    "target": "memory" | "user" | null,
    "content_hash": "<sha256 hex first-8>",
    "content_length": <int>,
    "query": "<str>" (session_search only),
    "result_count": <int> (session_search only),
    "result_session_ids": [<str>, ...] (session_search only, truncated to 10),
    "session_id": "<from HERMES_SESSION_ID env, or 'unknown'>"
  }

The log grows roughly proportional to memory + session_search activity —
expect ~few KB/day at single-user volume. Rotate manually if it exceeds
~50MB.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
from typing import Any

_LOG_PATH = Path.home() / ".hermes" / "logs" / "memory-shadow.log"


def _hash_first8(text: str) -> str:
    """Truncated sha256 hex for fast comparison without leaking content."""
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:8]


def _current_session_id() -> str:
    """Pull session_id from env; fall back to 'unknown' so the field is
    always present (consistent shape simplifies log parsing)."""
    return os.environ.get("HERMES_SESSION_ID", "unknown")


def _write(record: dict[str, Any]) -> None:
    """Append a record to memory-shadow.log. Never raises."""
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # Best-effort. Don't crash the agent on log failures.
        pass


def log_memory_write(action: str, target: str, content: str | None) -> None:
    """Record a memory_tool action (add/replace/remove)."""
    payload = content or ""
    _write({
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": "memory.write",
        "action": action,
        "target": target,
        "content_hash": _hash_first8(payload),
        "content_length": len(payload),
        "session_id": _current_session_id(),
    })


def log_memory_snapshot(memory_content: str, user_content: str) -> None:
    """Record the MemoryStore snapshot at session start (what the agent sees
    in its system prompt). Helps correlate 'what was injected' with 'what was
    later written.'"""
    _write({
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": "memory.read.snapshot",
        "target": "memory",
        "content_hash": _hash_first8(memory_content),
        "content_length": len(memory_content or ""),
        "session_id": _current_session_id(),
    })
    _write({
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": "memory.read.snapshot",
        "target": "user",
        "content_hash": _hash_first8(user_content),
        "content_length": len(user_content or ""),
        "session_id": _current_session_id(),
    })


def log_session_search(query: str, result_session_ids: list[str]) -> None:
    """Record a session_search invocation. Captures what historical sessions
    are surfaced when the agent picks this tool over Atlas."""
    _write({
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "event": "session_search.query",
        "query": (query or "")[:200],
        "result_count": len(result_session_ids),
        "result_session_ids": list(result_session_ids)[:10],
        "session_id": _current_session_id(),
    })
