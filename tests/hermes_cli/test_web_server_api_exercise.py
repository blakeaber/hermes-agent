"""End-to-end exercise of the hermes_cli.web_server API surface.

Two guarantees for the developer-portal consumers of this API:

1. ``test_unknown_api_path_returns_json_404`` — an authenticated request to a
   non-existent ``/api/*`` route must 404 as JSON, NOT fall through to the SPA
   catch-all and return ``200 text/html`` (the index page). A 200-HTML body for
   a missing endpoint silently breaks any generated API client that keys off the
   status code / content type. This is a real regression the SPA catch-all
   introduced: it swallows every unmatched path, including API typos.

2. ``test_every_endpoint_is_reachable_with_a_valid_token`` — enumerate the
   COMPLETE (method, path) set from ``app.openapi()`` (ground truth, matches the
   code) and prove each responds without an unexpected 5xx when called with a
   valid session token and a minimal schema-derived request.
"""

import tempfile
from pathlib import Path

import pytest

from starlette.testclient import TestClient
from fastapi import FastAPI

import hermes_cli.web_server as ws
from hermes_cli.web_server import app, _SESSION_HEADER_NAME, _SESSION_TOKEN


# ---------------------------------------------------------------------------
# 1. The SPA catch-all must not swallow unknown /api/* routes.
# ---------------------------------------------------------------------------

@pytest.fixture()
def spa_app(monkeypatch):
    """A fresh app with the SPA mounted against a minimal built frontend.

    Locally ``WEB_DIST`` does not exist, so the not-built fallback (which 404s
    everything) hides the catch-all bug. Point ``mount_spa`` at a temp dir that
    looks like a real build so the production ``serve_spa`` route is exercised.
    """
    d = Path(tempfile.mkdtemp())
    (d / "index.html").write_text("<html><head></head><body>SPA</body></html>")
    (d / "assets").mkdir()
    monkeypatch.setattr(ws, "WEB_DIST", d)
    fresh = FastAPI()
    ws.mount_spa(fresh)
    return TestClient(fresh)


def test_unknown_api_path_returns_json_404(spa_app):
    """GET /api/<typo> must be a JSON 404, not the SPA index (200 text/html)."""
    resp = spa_app.get("/api/this-endpoint-does-not-exist")
    assert resp.status_code == 404, (
        f"unknown /api path returned {resp.status_code} "
        f"({resp.headers.get('content-type')}) — the SPA catch-all is "
        f"swallowing API 404s"
    )
    assert "text/html" not in resp.headers.get("content-type", "")


def test_unknown_nested_api_path_returns_json_404(spa_app):
    resp = spa_app.get("/api/plugins/kanban/no-such-route")
    assert resp.status_code == 404
    assert "text/html" not in resp.headers.get("content-type", "")


def test_real_spa_route_still_serves_index(spa_app):
    """Client-side (non-/api) routes must still fall through to index.html."""
    resp = spa_app.get("/dashboard/some/client/route")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 2. Every endpoint is reachable with a valid token (no unexpected 5xx).
# ---------------------------------------------------------------------------

_PATH_PARAM_DEFAULTS = {
    "name": "gateway-restart", "job_id": "nope-job", "session_id": "nope-sess",
    "slug": "default", "task_id": "nope-task", "run_id": "1",
    "profile_name": "default", "provider_id": "openai", "platform": "slack",
    "plugin_name": "example", "file_path": "index.js", "full_path": "api/nope",
}


def _example(schema, comps, depth=0):
    if schema is None or depth > 6:
        return None
    if "$ref" in schema:
        return _example(comps.get(schema["$ref"].split("/")[-1], {}), comps, depth + 1)
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            for sub in schema[key]:
                if sub.get("type") != "null":
                    return _example(sub, comps, depth + 1)
    t = schema.get("type")
    if t == "object" or "properties" in schema:
        out = {}
        for pname in schema.get("required", []):
            out[pname] = _example(schema.get("properties", {}).get(pname, {}), comps, depth + 1)
        return out
    if t == "array":
        return []
    if t == "string":
        return schema["enum"][0] if "enum" in schema else "test"
    if t == "integer":
        return 1
    if t == "number":
        return 1.0
    if t == "boolean":
        return True
    return None


def _iter_endpoints():
    spec = app.openapi()
    comps = spec.get("components", {}).get("schemas", {})
    for path, methods in spec.get("paths", {}).items():
        for method, op in methods.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            yield method.upper(), path, op, comps


def test_openapi_catalog_is_nonempty():
    endpoints = list(_iter_endpoints())
    # The fork surface has ~100+ routes; guard against an empty/broken spec.
    assert len(endpoints) > 90


def test_every_endpoint_is_reachable_with_a_valid_token(_isolate_hermes_home):
    """No endpoint may return an unexpected 5xx for a minimal valid request.

    A deliberate 4xx (401/404/400/409/422) is acceptable — that is the endpoint
    handling bogus input on purpose. A 5xx / uncaught exception is a defect.
    """
    client = TestClient(app, raise_server_exceptions=False)
    client.headers[_SESSION_HEADER_NAME] = _SESSION_TOKEN

    failures = []
    count = 0
    for method, path, op, comps in _iter_endpoints():
        count += 1
        url = path
        query = {}
        for prm in op.get("parameters", []):
            pname = prm.get("name")
            val = _example(prm.get("schema", {}), comps)
            if prm.get("in") == "path":
                if val in (None, "test"):
                    val = _PATH_PARAM_DEFAULTS.get(pname, "test")
                url = url.replace("{%s}" % pname, str(val))
            elif prm.get("in") == "query" and prm.get("required") and val is not None:
                query[pname] = val
        for k, v in _PATH_PARAM_DEFAULTS.items():
            url = url.replace("{%s}" % k, str(v))

        body = None
        rb = op.get("requestBody")
        if rb:
            js = rb.get("content", {}).get("application/json")
            if js:
                body = _example(js.get("schema", {}), comps)

        kwargs = {}
        if query:
            kwargs["params"] = query
        if body is not None:
            kwargs["json"] = body
        resp = client.request(method, url, **kwargs)
        if resp.status_code >= 500:
            failures.append(f"{method} {path} -> {resp.status_code}: {resp.text[:160]}")

    assert count > 90, f"only enumerated {count} endpoints"
    assert not failures, "endpoints returned unexpected 5xx:\n" + "\n".join(failures)
