"""Plan 037-B: `_find_all_skills` sources from the Skills Service when one is
configured (HERMES_SKILLS_SERVICE_URL), and falls back to local filesystem
discovery when the service is unset or unreachable.

The service client (`agent.skill_utils.skills_service_list`) already existed but
had no call site on the `hermes skills list` path; these tests guard the wiring.
"""

from __future__ import annotations

import agent.skill_utils as skill_utils
from tools.skills_tool import _find_all_skills


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
