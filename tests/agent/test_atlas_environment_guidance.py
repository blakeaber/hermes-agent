"""Tests for ATLAS_ENVIRONMENT_GUIDANCE — tells Hermes its email/calendar
live in Atlas (queryable via ``atlas_ask``) and that it holds no Google OAuth
of its own, so it should STOP asking the user for credentials.

Regression for the deployed Slack bot hallucinating Gmail/Calendar tools and
asking Blake to "configure Google Workspace credentials" — credentials cloud
Hermes neither has nor needs.
"""

from unittest.mock import MagicMock, patch

import pytest

from run_agent import AIAgent


def _make_tool_defs(*names: str) -> list:
    """Build minimal tool definition list accepted by AIAgent.__init__.

    Mirrors the helper in ``tests/run_agent/test_run_agent.py``.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": n,
                "description": f"{n} tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for n in names
    ]


@pytest.fixture()
def agent_with_memory_tool():
    """Agent whose valid_tool_names includes 'memory'.

    Reuses the exact construction pattern of the ``agent_with_memory_tool``
    fixture in ``tests/run_agent/test_run_agent.py``.
    """
    with (
        patch(
            "run_agent.get_tool_definitions",
            return_value=_make_tool_defs("web_search", "memory"),
        ),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        a = AIAgent(
            api_key="test-k...7890",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
        a.client = MagicMock()
        return a


class TestAtlasEnvironmentGuidanceConstant:
    def test_constant_mentions_atlas_email_calendar_and_atlas_ask(self):
        from agent.prompt_builder import ATLAS_ENVIRONMENT_GUIDANCE

        text = ATLAS_ENVIRONMENT_GUIDANCE.lower()
        assert "atlas" in text
        assert "calendar" in text
        assert "email" in text
        # Literal tool name must survive lowercasing (it's already lowercase).
        assert "atlas_ask" in ATLAS_ENVIRONMENT_GUIDANCE

    def test_constant_tells_agent_not_to_ask_for_credentials(self):
        from agent.prompt_builder import ATLAS_ENVIRONMENT_GUIDANCE

        text = ATLAS_ENVIRONMENT_GUIDANCE.lower()
        assert "do not ask" in text or "don't ask" in text
        assert "credential" in text or "oauth" in text


class TestAtlasEnvironmentGuidanceInjection:
    def test_injected_into_stable_tier_with_memory_tool(self, agent_with_memory_tool):
        from agent.system_prompt import build_system_prompt_parts

        stable = build_system_prompt_parts(agent_with_memory_tool)["stable"]
        assert "atlas_ask" in stable
        lowered = stable.lower()
        assert "ingested into atlas" in lowered or "auto-ingest" in lowered
