"""hermes-081-C (AGE-703) — ``/hermes status`` platform + integration-health + routing transparency.

Additive surface that answers, when a user runs ``/hermes status`` (or the
``status`` builtin), three transparency questions:

1. **Connected platforms** — derived from the gateway runtime status file
   (``gateway.status.read_runtime_status``), the same source the gateway writes
   ``platform_state="connected"`` into as each adapter connects.
2. **Integration health** — best-effort reachability of Atlas, the orchestrator
   sensor, and the skills-service, keyed off their configured base-URL env vars.
   Fail-soft by construction (mirrors ``gateway.atlas_wiki_client`` /
   ``clarify_relay``): an unconfigured integration reports ``"unknown"`` and an
   unreachable one reports ``"unreachable"`` — the surface never raises.
3. **Routing table** — every gateway-available command classified as a native
   Slack slash (``/model``) vs. a ``/hermes <cmd>``-routed command (e.g.
   ``/status``, which collides with a Slack built-in), built from the single
   source of truth in ``hermes_cli.commands``.

Output mirrors the sibling gateway surfaces (``gateway.wiki_surface`` /
``gateway.work_surface``): a pure ``build_status_view`` returns the structured
data, and ``render_status_blocks`` turns it into Slack Block Kit.

The module also exposes a ``handle(event_type, context)`` coroutine conforming
to :class:`gateway.hooks.HookRegistry`'s handler protocol, so it can be wired in
via ``HookRegistry._register_builtin_hooks`` as an always-on builtin. It is
additive and gated to the ``status`` command (returns ``None`` for anything
else), so it changes no existing behavior until registered.
"""

from __future__ import annotations

import os
from typing import Any, Awaitable, Callable

# Integration name → base-URL env var. The env names match the existing wiring:
# ATLAS_BASE_URL (gateway.atlas_wiki_client) and ORCHESTRATOR_SENSOR_URL
# (gateway.clarify_relay). HERMES_SKILLS_SERVICE_URL is the skills-service seam.
INTEGRATIONS: tuple[tuple[str, str], ...] = (
    ("atlas", "ATLAS_BASE_URL"),
    ("orchestrator", "ORCHESTRATOR_SENSOR_URL"),
    ("skills-service", "HERMES_SKILLS_SERVICE_URL"),
)

_PROBE_TIMEOUT_S = 5.0
_HEALTH_PATH = "/health"

# Type of an injectable async health prober: (name, base_url) -> health dict.
Prober = Callable[[str, str], Awaitable[dict[str, Any]]]


# ---------------------------------------------------------------------------
# 1. Connected platforms
# ---------------------------------------------------------------------------

def _platform_label(name: str) -> str:
    try:
        from hermes_cli.platforms import platform_label  # noqa: PLC0415

        return platform_label(name, default=name) or name
    except Exception:  # noqa: BLE001 — display label is best-effort.
        return name


def collect_connected_platforms() -> list[dict[str, Any]]:
    """Return connected/known messaging platforms from gateway runtime status.

    Reads ``gateway.status.read_runtime_status`` (the live per-platform state the
    gateway persists). Fails soft to ``[]`` — a missing/broken status file must
    never break the status surface.
    """
    try:
        from gateway.status import read_runtime_status  # noqa: PLC0415

        status = read_runtime_status() or {}
    except Exception:  # noqa: BLE001 — fail-soft: no status is not an error.
        return []

    platforms = status.get("platforms") if isinstance(status, dict) else None
    if not isinstance(platforms, dict):
        return []

    result: list[dict[str, Any]] = []
    for name, meta in sorted(platforms.items()):
        state = (meta or {}).get("state", "unknown") if isinstance(meta, dict) else "unknown"
        result.append(
            {
                "name": name,
                "label": _platform_label(name),
                "state": state,
                "connected": state == "connected",
            }
        )
    return result


# ---------------------------------------------------------------------------
# 2. Integration health (best-effort, fail-soft)
# ---------------------------------------------------------------------------

async def _default_prober(name: str, base_url: str) -> dict[str, Any]:
    """Best-effort ``GET {base_url}/health``. Never raises; returns a flag dict.

    Mirrors the fail-soft aiohttp pattern in ``gateway.atlas_wiki_client``.
    """
    url = base_url.rstrip("/") + _HEALTH_PATH
    try:
        import aiohttp  # noqa: PLC0415

        timeout = aiohttp.ClientTimeout(total=_PROBE_TIMEOUT_S)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if 200 <= resp.status < 300:
                    return {"reachable": True, "status": "ok", "http": resp.status}
                return {
                    "reachable": False,
                    "status": "unreachable",
                    "http": resp.status,
                }
    except Exception as exc:  # noqa: BLE001 — fail-soft: report, don't raise.
        return {"reachable": False, "status": "unreachable", "detail": str(exc)}


async def collect_integration_health(*, prober: Prober | None = None) -> dict[str, dict[str, Any]]:
    """Probe Atlas, the orchestrator, and the skills-service; fail-soft.

    An unconfigured integration (base-URL env unset) reports
    ``{"configured": False, "status": "unknown", "reachable": False}`` without
    any network call. A configured one is probed via *prober* (injectable for
    hermetic tests; defaults to :func:`_default_prober`). Any exception from the
    prober degrades to ``"unreachable"`` rather than propagating.
    """
    prober = prober or _default_prober
    out: dict[str, dict[str, Any]] = {}
    for name, env in INTEGRATIONS:
        base = os.environ.get(env, "").strip()
        if not base:
            out[name] = {
                "reachable": False,
                "status": "unknown",
                "configured": False,
                "reason": f"{env} unset",
            }
            continue
        try:
            res = await prober(name, base)
        except Exception as exc:  # noqa: BLE001 — fail-soft even if prober throws.
            res = {"reachable": False, "status": "unreachable", "detail": str(exc)}
        if not isinstance(res, dict):
            res = {"reachable": False, "status": "unknown"}
        res.setdefault("reachable", False)
        res.setdefault("status", "unknown")
        res["configured"] = True
        out[name] = res
    return out


# ---------------------------------------------------------------------------
# 3. Routing table
# ---------------------------------------------------------------------------

def build_routing_table() -> list[dict[str, str]]:
    """Classify every gateway-available command as native-slash vs hermes-routed.

    Built from the single source of truth in ``hermes_cli.commands``:
    ``COMMAND_REGISTRY`` for the command set and ``slack_native_slashes()`` for
    which names actually surface as standalone Slack slashes. A command whose
    sanitized name is not a native slash (dropped by the Slack 50-command clamp
    or colliding with a Slack built-in like ``/status``) is only reachable as
    ``/hermes <cmd>``. CLI-only commands (no gateway surface) are excluded.
    """
    from hermes_cli.commands import (  # noqa: PLC0415
        COMMAND_REGISTRY,
        _is_gateway_available,
        _sanitize_slack_name,
        slack_native_slashes,
    )

    native_names = {name for name, _desc, _hint in slack_native_slashes()}

    rows: list[dict[str, str]] = []
    for cmd in COMMAND_REGISTRY:
        if not _is_gateway_available(cmd):
            continue
        slug = _sanitize_slack_name(cmd.name)
        if slug and slug in native_names:
            rows.append(
                {"command": cmd.name, "routing": "native-slash", "invoke": f"/{slug}"}
            )
        else:
            rows.append(
                {"command": cmd.name, "routing": "hermes-routed", "invoke": f"/hermes {cmd.name}"}
            )
    return rows


# ---------------------------------------------------------------------------
# Assembled view
# ---------------------------------------------------------------------------

async def build_status_view(*, prober: Prober | None = None) -> dict[str, Any]:
    """Assemble the three transparency sections into one structured view."""
    return {
        "platforms": collect_connected_platforms(),
        "integrations": await collect_integration_health(prober=prober),
        "routing": build_routing_table(),
    }


# ---------------------------------------------------------------------------
# Slack Block Kit render (mirrors gateway.wiki_surface conventions)
# ---------------------------------------------------------------------------

def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _platform_line(p: dict[str, Any]) -> str:
    icon = "🟢" if p.get("connected") else "🔴"
    return f"{icon} `{p['name']}` — {p.get('state', 'unknown')}"


def _integration_line(name: str, health: dict[str, Any]) -> str:
    status = health.get("status", "unknown")
    icon = {"ok": "🟢", "unreachable": "🔴", "unknown": "⚪️"}.get(status, "⚪️")
    if not health.get("configured", False):
        return f"{icon} `{name}` — not configured"
    return f"{icon} `{name}` — {status}"


def render_status_blocks(view: dict[str, Any]) -> list[dict[str, Any]]:
    """Render a status view into Slack Block Kit blocks."""
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Hermes status"}},
    ]

    # 1. Platforms
    platforms = view.get("platforms") or []
    if platforms:
        lines = "\n".join(_platform_line(p) for p in platforms)
    else:
        lines = "_no platform status available_"
    blocks.append(_section(f"*Platforms*\n{lines}"))

    # 2. Integrations
    blocks.append({"type": "divider"})
    integrations = view.get("integrations") or {}
    if integrations:
        int_lines = "\n".join(
            _integration_line(name, health) for name, health in integrations.items()
        )
    else:
        int_lines = "_no integrations probed_"
    blocks.append(_section(f"*Integrations*\n{int_lines}"))

    # 3. Routing
    blocks.append({"type": "divider"})
    routing = view.get("routing") or []
    native = [r for r in routing if r["routing"] == "native-slash"]
    routed = [r for r in routing if r["routing"] == "hermes-routed"]
    routing_summary = (
        f"*Routing* — {len(native)} native slash · {len(routed)} `/hermes <cmd>`-routed"
    )
    routed_names = ", ".join(f"`{r['invoke']}`" for r in routed) or "_none_"
    blocks.append(_section(f"{routing_summary}\n`/hermes <cmd>`-only: {routed_names}"))

    return blocks


# ---------------------------------------------------------------------------
# Registerable builtin-hook entrypoint
# ---------------------------------------------------------------------------

_STATUS_EVENTS = {"command:status", "command:hermes_status"}


async def handle(event_type: str, context: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Hook entrypoint: surface the status view for the ``status`` command.

    Conforms to :class:`gateway.hooks.HookRegistry`'s ``handle(event_type,
    context)`` protocol. Returns ``None`` (no-op) for any non-status event so it
    is safe to register for ``command:*``. For a status event it returns
    ``{"view": ..., "blocks": ...}``. Never raises — a broken status probe must
    not break command dispatch.
    """
    if event_type not in _STATUS_EVENTS:
        return None
    context = context or {}
    prober = context.get("prober")
    try:
        view = await build_status_view(prober=prober)
        return {"view": view, "blocks": render_status_blocks(view)}
    except Exception:  # noqa: BLE001 — fail-soft: never break dispatch.
        return None


__all__ = [
    "INTEGRATIONS",
    "Prober",
    "build_routing_table",
    "build_status_view",
    "collect_connected_platforms",
    "collect_integration_health",
    "handle",
    "render_status_blocks",
]
