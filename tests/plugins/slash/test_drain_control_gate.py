"""HERMES_DRAIN_CONTROL gate — the honesty fix.

In this deployment drain control is NOT wired (no ``temporalio`` in the Hermes
image, no ``TEMPORAL_HOST`` in the env), so ``/resume`` + ``/skip`` and the
🔄/⏭/🛑 reaction handlers can never signal the drain workflow — they used to
present as available and then fail with a misleading ":x: ... check that
TEMPORAL_HOST is reachable". This gate makes the surface honest: when
``HERMES_DRAIN_CONTROL`` is off (the default), the commands are NOT registered
(hidden from the menu) and reactions stay silent. Flip ``HERMES_DRAIN_CONTROL=1``
(after wiring temporalio + TEMPORAL_HOST) to re-enable.
"""

from __future__ import annotations

import pytest

from plugins.slash import orchestrator as slash_mod
from plugins.slash import register
from plugins.slash.orchestrator import handle_reaction_event

_ESC = "[escalation] phase=020-E failed after 2 retries. React 🛑 to halt."


class _Ctx:
    """Minimal PluginContext stub capturing registered command names."""

    def __init__(self) -> None:
        self.registered: list[str] = []

    def register_command(self, name, *, handler, description, args_hint="") -> None:
        self.registered.append(name)


def test_reaction_silent_when_drain_control_disabled(monkeypatch):
    monkeypatch.delenv("HERMES_DRAIN_CONTROL", raising=False)
    fired: list = []
    monkeypatch.setattr(slash_mod, "_signal_halt_sync", lambda reason: fired.append(reason))
    note = handle_reaction_event(emoji_name="octagonal_sign", message_text=_ESC)
    assert note is None
    assert fired == [], "the dead Temporal signal must never be attempted when disabled"


def test_reaction_fires_when_drain_control_enabled(monkeypatch):
    monkeypatch.setenv("HERMES_DRAIN_CONTROL", "1")
    fired: list = []
    monkeypatch.setattr(slash_mod, "_signal_halt_sync", lambda reason: fired.append(reason))
    note = handle_reaction_event(emoji_name="octagonal_sign", message_text=_ESC)
    assert note is not None and fired, "enabled → the reaction fires the halt signal"


def test_resume_skip_not_registered_when_disabled(monkeypatch):
    monkeypatch.delenv("HERMES_DRAIN_CONTROL", raising=False)
    ctx = _Ctx()
    register(ctx)
    assert "resume" not in ctx.registered
    assert "skip" not in ctx.registered
    # the always-on commands remain so we don't regress the working surface
    assert "daily" in ctx.registered and "draft" in ctx.registered


def test_resume_skip_registered_when_enabled(monkeypatch):
    monkeypatch.setenv("HERMES_DRAIN_CONTROL", "1")
    ctx = _Ctx()
    register(ctx)
    assert "resume" in ctx.registered and "skip" in ctx.registered
