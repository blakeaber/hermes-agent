"""Tests for the Atlas memory provider `atlas_ingest_status` tool (Plan 038-A).

Wraps Atlas `GET /v1/stats` (army-of-one
`backend/src/atlas/api/stats_routes.py` — StatsResponse). The tool reports
what data (email/calendar/contacts/etc.) is ingested and when it was last
refreshed, so Hermes can give Blake a grounded answer to "is my email/calendar
actually ingested?" instead of guessing. All network calls are mocked; no live
Atlas required.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "memory" / "atlas" / "__init__.py"


def _load_provider_module():
    spec = importlib.util.spec_from_file_location("atlas_provider_ingest_under_test", _PLUGIN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return _load_provider_module()


@pytest.fixture
def provider(mod, monkeypatch):
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.test:8000")
    monkeypatch.setenv("ATLAS_BEARER_TOKEN", "test-token")
    monkeypatch.setenv("ATLAS_AGENT_NAME", "hermes")
    p = mod.AtlasMemoryProvider()
    p.initialize(session_id="sess-ingest", hermes_home="/tmp", platform="cli")
    return p


# A representative /v1/stats payload (trimmed to the fields the tool reads).
_FAKE_STATS = {
    "corpus": {
        "chunks_total": 1234,
        "entities_total": 88,
        "triples_total": 4096,
        "sources_total": 5,
        "embedding_coverage_pct": 99.1,
        "top_sources": [
            {"source_iri": "urn:gmail:thread", "chunks": 800},
            {"source_iri": "urn:calendar:event", "chunks": 300},
            {"source_iri": "urn:pipedrive:activity", "chunks": 134},
        ],
    },
    "jobs": {
        "last_7_days": {"gmail": 42, "calendar": 12, "pipedrive": 3},
        "last_30_days": {"gmail": 120, "calendar": 40, "pipedrive": 9},
        "recent_failures": [],
    },
    "cost": {
        "today_usd": 0.0, "last_7_days_usd": 0.0, "last_30_days_usd": 0.0,
        "month_to_date_usd": 0.0, "budget_monthly_usd": 0.0,
        "budget_remaining_usd": 0.0, "by_model_last_7d": {},
    },
    "cost_summary": {
        "last_30_days_usd": 0.0, "month_to_date_usd": 0.0,
        "budget_remaining_usd": 0.0, "details_endpoint": "/v1/stats/llm",
    },
    "ingest": {
        "last_ingest_at": "2026-06-03T18:22:11Z",
        "ingest_rate_last_7d_per_day": 8.14,
    },
    "confidence": {
        "low_confidence_triples_count": 0,
        "avg_confidence_last_30d": None,
        "total_evidence_events": 0,
    },
}


# ---------------------------------------------------------------------------
# Schema / registration
# ---------------------------------------------------------------------------


def test_ingest_status_tool_in_schema_list(provider):
    names = {t["name"] for t in provider.get_tool_schemas()}
    assert "atlas_ingest_status" in names


def test_ingest_status_schema_has_no_required_args(provider):
    schemas = {t["name"]: t for t in provider.get_tool_schemas()}
    schema = schemas["atlas_ingest_status"]
    assert schema["parameters"]["required"] == []
    desc = schema["description"].lower()
    assert "ingest" in desc
    assert "up to date" in desc or "refreshed" in desc


def test_register_exposes_ingest_status(mod):
    captured: dict[str, object] = {}

    class FakeCtx:
        def register_memory_provider(self, p):
            captured["provider"] = p

    mod.register(FakeCtx())
    p = captured["provider"]
    names = {t["name"] for t in p.get_tool_schemas()}
    assert "atlas_ingest_status" in names


# ---------------------------------------------------------------------------
# Tool call behavior — mocked HTTP
# ---------------------------------------------------------------------------


def test_ingest_status_summarizes_sources_and_recency(provider, mod, monkeypatch):
    """Returns a human-readable summary naming sources + counts + recency."""
    import httpx

    captured: dict[str, object] = {}

    class FakeResp:
        def raise_for_status(self): ...
        def json(self):
            return _FAKE_STATS

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(httpx, "get", fake_get)

    raw = provider.handle_tool_call("atlas_ingest_status", {})
    payload = json.loads(raw)
    summary = payload["result"] if isinstance(payload, dict) and "result" in payload else raw
    low = summary.lower()

    # Names the sources the fake returns
    assert "calendar" in low
    assert "gmail" in low or "email" in low
    # Surfaces counts
    assert "800" in summary or "300" in summary or "42" in summary or "12" in summary
    # Surfaces recency
    assert "2026-06-03" in summary

    # Wire contract
    assert captured["url"].endswith("/v1/stats")
    assert captured["headers"]["Authorization"] == "Bearer test-token"


def test_ingest_status_handles_empty_corpus(provider, monkeypatch):
    import httpx

    empty = {
        "corpus": {"chunks_total": 0, "entities_total": 0, "triples_total": 0,
                   "sources_total": 0, "embedding_coverage_pct": 0.0,
                   "top_sources": []},
        "jobs": {"last_7_days": {}, "last_30_days": {}, "recent_failures": []},
        "cost": {"today_usd": 0.0, "last_7_days_usd": 0.0, "last_30_days_usd": 0.0,
                 "month_to_date_usd": 0.0, "budget_monthly_usd": 0.0,
                 "budget_remaining_usd": 0.0, "by_model_last_7d": {}},
        "cost_summary": {"last_30_days_usd": 0.0, "month_to_date_usd": 0.0,
                         "budget_remaining_usd": 0.0, "details_endpoint": "/v1/stats/llm"},
        "ingest": {"last_ingest_at": None, "ingest_rate_last_7d_per_day": 0.0},
        "confidence": {"low_confidence_triples_count": 0,
                       "avg_confidence_last_30d": None, "total_evidence_events": 0},
    }

    class FakeResp:
        def raise_for_status(self): ...
        def json(self):
            return empty

    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResp())

    raw = provider.handle_tool_call("atlas_ingest_status", {})
    payload = json.loads(raw)
    summary = payload["result"] if isinstance(payload, dict) and "result" in payload else raw
    # No data should be reported clearly, not as an error.
    assert "no" in summary.lower() or "0" in summary or "nothing" in summary.lower()


def test_ingest_status_500_records_failure_and_returns_error(provider, monkeypatch):
    import httpx

    class FakeResp:
        status_code = 500
        def raise_for_status(self):
            raise httpx.HTTPStatusError("500", request=None, response=self)
        def json(self):
            return {}

    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResp())

    before = provider._consecutive_failures
    result = provider.handle_tool_call("atlas_ingest_status", {})
    assert "error" in result.lower() or "failed" in result.lower()
    assert provider._consecutive_failures == before + 1


def test_ingest_status_breaker_short_circuits(provider, mod, monkeypatch):
    import httpx

    def boom(*a, **k):
        raise httpx.ReadTimeout("atlas timed out")

    monkeypatch.setattr(httpx, "get", boom)
    for _ in range(mod._BREAKER_THRESHOLD):
        provider.handle_tool_call("atlas_ingest_status", {})
    assert provider._is_breaker_open() is True

    short = json.loads(provider.handle_tool_call("atlas_ingest_status", {}))
    assert "unavailable" in short["error"].lower()
