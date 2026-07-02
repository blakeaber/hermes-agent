"""hermes-081-C (AGE-703) — /hermes status transparency surface tests.

Hermetic: the connected-platforms source (``gateway.status.read_runtime_status``)
is monkeypatched, and integration health uses an injected fake ``prober`` so no
network I/O ever happens. The routing table is derived from the real command
registry (pure, deterministic).
"""

from __future__ import annotations

import asyncio

import pytest

from gateway.builtin_hooks import hermes_status as hs


# ---------------------------------------------------------------------------
# 1. Connected platforms (derived from gateway runtime status)
# ---------------------------------------------------------------------------

def test_connected_platforms_reflect_runtime_status(monkeypatch):
    monkeypatch.setattr(
        "gateway.status.read_runtime_status",
        lambda: {
            "platforms": {
                "slack": {"state": "connected"},
                "telegram": {"state": "failed"},
            }
        },
    )
    platforms = hs.collect_connected_platforms()
    by_name = {p["name"]: p for p in platforms}
    assert by_name["slack"]["connected"] is True
    assert by_name["slack"]["state"] == "connected"
    assert by_name["telegram"]["connected"] is False
    # A human label is attached for display.
    assert by_name["slack"]["label"]


def test_connected_platforms_fail_soft_when_status_unavailable(monkeypatch):
    def _boom():
        raise RuntimeError("no gateway running")

    monkeypatch.setattr("gateway.status.read_runtime_status", _boom)
    # Never raises; returns an empty list rather than blowing up the surface.
    assert hs.collect_connected_platforms() == []


# ---------------------------------------------------------------------------
# 2. Integration health for atlas / orchestrator / skills-service
# ---------------------------------------------------------------------------

async def _ok_prober(name, base_url):
    return {"reachable": True, "status": "ok", "http": 200}


async def _raising_prober(name, base_url):
    raise ConnectionError("boom")


def test_integration_health_covers_all_three_integrations(monkeypatch):
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.local")
    monkeypatch.setenv("ORCHESTRATOR_SENSOR_URL", "http://orch.local")
    monkeypatch.setenv("HERMES_SKILLS_SERVICE_URL", "http://skills.local")

    health = asyncio.run(hs.collect_integration_health(prober=_ok_prober))

    assert set(health) == {"atlas", "orchestrator", "skills-service"}
    for name in ("atlas", "orchestrator", "skills-service"):
        assert health[name]["reachable"] is True
        assert health[name]["status"] == "ok"
        assert health[name]["configured"] is True


def test_integration_health_unset_env_is_unknown_not_error(monkeypatch):
    monkeypatch.delenv("ATLAS_BASE_URL", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_SENSOR_URL", raising=False)
    monkeypatch.delenv("HERMES_SKILLS_SERVICE_URL", raising=False)

    health = asyncio.run(hs.collect_integration_health(prober=_ok_prober))
    for name in ("atlas", "orchestrator", "skills-service"):
        assert health[name]["configured"] is False
        assert health[name]["status"] == "unknown"
        assert health[name]["reachable"] is False


def test_integration_health_fails_soft_when_prober_raises(monkeypatch):
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.local")
    monkeypatch.setenv("ORCHESTRATOR_SENSOR_URL", "http://orch.local")
    monkeypatch.setenv("HERMES_SKILLS_SERVICE_URL", "http://skills.local")

    health = asyncio.run(hs.collect_integration_health(prober=_raising_prober))
    for name in ("atlas", "orchestrator", "skills-service"):
        assert health[name]["reachable"] is False
        assert health[name]["status"] == "unreachable"


# ---------------------------------------------------------------------------
# 3. Routing table: native-slash vs /hermes <cmd>-routed
# ---------------------------------------------------------------------------

def test_routing_table_classifies_native_vs_hermes_routed():
    rows = hs.build_routing_table()
    by_cmd = {r["command"]: r for r in rows}

    # A plain gateway command with a Slack-legal name is a native slash.
    assert by_cmd["model"]["routing"] == "native-slash"
    assert by_cmd["model"]["invoke"] == "/model"

    # 'status' collides with a Slack built-in slash → only reachable as
    # /hermes status (the very command this surface backs).
    assert by_cmd["status"]["routing"] == "hermes-routed"
    assert by_cmd["status"]["invoke"] == "/hermes status"

    # Every row carries the three transparency fields.
    for r in rows:
        assert set(r) == {"command", "routing", "invoke"}
        assert r["routing"] in {"native-slash", "hermes-routed"}


def test_routing_table_excludes_cli_only_commands():
    rows = hs.build_routing_table()
    names = {r["command"] for r in rows}
    # 'config' is cli_only with no gateway gate — not reachable in Slack at all.
    assert "config" not in names


# ---------------------------------------------------------------------------
# Assembled view + Block Kit render
# ---------------------------------------------------------------------------

def test_build_status_view_has_three_sections(monkeypatch):
    monkeypatch.setattr(
        "gateway.status.read_runtime_status",
        lambda: {"platforms": {"slack": {"state": "connected"}}},
    )
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.local")
    monkeypatch.delenv("ORCHESTRATOR_SENSOR_URL", raising=False)
    monkeypatch.delenv("HERMES_SKILLS_SERVICE_URL", raising=False)

    view = asyncio.run(hs.build_status_view(prober=_ok_prober))

    assert set(view) == {"platforms", "integrations", "routing"}
    assert any(p["name"] == "slack" for p in view["platforms"])
    assert set(view["integrations"]) == {"atlas", "orchestrator", "skills-service"}
    assert view["routing"]


def test_build_status_view_never_raises_on_probe_failure(monkeypatch):
    monkeypatch.setattr("gateway.status.read_runtime_status", lambda: {})
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.local")
    monkeypatch.setenv("ORCHESTRATOR_SENSOR_URL", "http://orch.local")
    monkeypatch.setenv("HERMES_SKILLS_SERVICE_URL", "http://skills.local")

    view = asyncio.run(hs.build_status_view(prober=_raising_prober))
    # All three integrations degrade to unreachable; nothing raises.
    assert all(v["reachable"] is False for v in view["integrations"].values())


def test_render_status_blocks_is_slack_block_kit(monkeypatch):
    monkeypatch.setattr(
        "gateway.status.read_runtime_status",
        lambda: {"platforms": {"slack": {"state": "connected"}}},
    )
    monkeypatch.setenv("ATLAS_BASE_URL", "http://atlas.local")
    monkeypatch.delenv("ORCHESTRATOR_SENSOR_URL", raising=False)
    monkeypatch.delenv("HERMES_SKILLS_SERVICE_URL", raising=False)

    view = asyncio.run(hs.build_status_view(prober=_ok_prober))
    blocks = hs.render_status_blocks(view)

    # Valid Block Kit: a header plus section blocks with mrkdwn text.
    assert blocks[0]["type"] == "header"
    assert any(b.get("type") == "section" for b in blocks)
    rendered = "\n".join(
        b["text"]["text"] for b in blocks if b.get("type") == "section"
    )
    # The three sections are all present in the rendered surface.
    assert "Platforms" in rendered
    assert "Integrations" in rendered
    assert "Routing" in rendered
    assert "atlas" in rendered
    assert "slack" in rendered


def test_handle_hook_signature_returns_view(monkeypatch):
    """The module is a registerable builtin hook: handle(event_type, context)."""
    monkeypatch.setattr("gateway.status.read_runtime_status", lambda: {})
    monkeypatch.delenv("ATLAS_BASE_URL", raising=False)
    monkeypatch.delenv("ORCHESTRATOR_SENSOR_URL", raising=False)
    monkeypatch.delenv("HERMES_SKILLS_SERVICE_URL", raising=False)

    # Non-status command → hook is a no-op (returns None).
    assert asyncio.run(hs.handle("command:model", {})) is None

    # /hermes status (or the status builtin) → returns a structured view + blocks.
    result = asyncio.run(hs.handle("command:status", {"prober": _ok_prober}))
    assert result is not None
    assert set(result["view"]) == {"platforms", "integrations", "routing"}
    assert result["blocks"][0]["type"] == "header"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
