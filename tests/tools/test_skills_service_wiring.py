"""Plan 037-B: `_find_all_skills` sources from the Skills Service when one is
configured (HERMES_SKILLS_SERVICE_URL), and falls back to local filesystem
discovery when the service is unset or unreachable.

The service client (`agent.skill_utils.skills_service_list`) already existed but
had no call site on the `hermes skills list` path; these tests guard the wiring.
"""

from __future__ import annotations

import json

import agent.skill_utils as skill_utils
from tools.skills_tool import _find_all_skills, skill_view


_SERVICE_SKILL = "svc-only-skill-037b"


def test_find_all_skills_uses_service_when_available(monkeypatch):
    """When the service returns entries, they are returned (mapped to the local
    metadata shape) instead of local discovery."""
    service_response = [
        {
            "name": _SERVICE_SKILL,
            "description": "A skill served by the Skills Service.",
            "scope": "team",
            "registry_name": "team-registry",
            "shadowing": [],
        }
    ]
    monkeypatch.setattr(skill_utils, "skills_service_list", lambda *a, **k: service_response)

    result = _find_all_skills()

    assert [s["name"] for s in result] == [_SERVICE_SKILL]
    entry = result[0]
    # Mapped into the local shape the CLI/banner/web callers expect.
    assert set(entry) >= {"name", "description", "category", "scope", "shadowing"}
    assert entry["scope"] == "team"
    # Service has no `category`; we group by the registry name.
    assert entry["category"] == "team-registry"


def test_find_all_skills_falls_back_to_local_when_no_service(monkeypatch):
    """When no service is configured (client returns None), discovery is local —
    the service-only skill must not appear."""
    monkeypatch.setattr(skill_utils, "skills_service_list", lambda *a, **k: None)

    result = _find_all_skills()

    assert isinstance(result, list)
    assert _SERVICE_SKILL not in {s["name"] for s in result}


def test_find_all_skills_falls_back_when_service_shape_unexpected(monkeypatch):
    """A malformed (non-list, non-{'skills':[...]}) response falls back to local
    rather than raising."""
    monkeypatch.setattr(skill_utils, "skills_service_list", lambda *a, **k: 12345)

    result = _find_all_skills()

    assert isinstance(result, list)
    assert _SERVICE_SKILL not in {s["name"] for s in result}


# ---------------------------------------------------------------------------
# Plan 039-A2: skill_view loads via the Skills Service first, filesystem
# fallback.  Mirrors the LIST wiring above so VIEW and LIST are consistent.
# ---------------------------------------------------------------------------

_VIEW_SERVICE_SKILL = "svc-only-skill-039"


def _write_local_skill(skills_dir, name):
    """Create a minimal on-disk SKILL.md so the filesystem fallback has a hit."""
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Local {name}.\n---\n\n# {name}\n\nLocal body.\n"
    )
    return skill_dir


def test_skill_view_loads_from_service_when_available(tmp_path, monkeypatch):
    """A skill that exists ONLY in the service (not on disk) is still loaded by
    skill_view via the service client — the canonical-source keystone."""
    from unittest.mock import patch

    service_content = (
        f"---\nname: {_VIEW_SERVICE_SKILL}\n"
        "description: Served by the Skills Service.\n---\n\n"
        f"# {_VIEW_SERVICE_SKILL}\n\nThis content came from the service.\n"
    )
    monkeypatch.setattr(
        skill_utils,
        "skills_service_view",
        lambda name, scope=None: {"content": service_content}
        if name == _VIEW_SERVICE_SKILL
        else None,
    )

    # Empty SKILLS_DIR — the skill does NOT exist on the filesystem.
    with patch("tools.skills_tool.SKILLS_DIR", tmp_path):
        raw = skill_view(_VIEW_SERVICE_SKILL)

    result = json.loads(raw)
    assert result["success"] is True
    assert result["name"] == _VIEW_SERVICE_SKILL
    assert "This content came from the service." in result["content"]
    # Loaded from the service — no local directory on disk.
    assert result["skill_dir"] is None


def test_skill_view_falls_back_to_filesystem_when_service_none(tmp_path, monkeypatch):
    """When the service returns None (unset / unavailable / 404), skill_view
    still loads a real filesystem skill — the fallback stays intact."""
    from unittest.mock import patch

    monkeypatch.setattr(skill_utils, "skills_service_view", lambda *a, **k: None)

    with patch("tools.skills_tool.SKILLS_DIR", tmp_path):
        _write_local_skill(tmp_path, "local-skill-039")
        raw = skill_view("local-skill-039")

    result = json.loads(raw)
    assert result["success"] is True
    assert result["name"] == "local-skill-039"
    assert "Local body." in result["content"]
    assert result["skill_dir"] is not None
