"""
Tests for hermes_agent/prompts/verifier_summary.py
"""

from __future__ import annotations

import json
import pytest

from hermes_agent.prompts.verifier_summary import (
    VALID_VERDICTS,
    VerifierSummary,
    build_prompt,
    parse_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raw(
    verdict: str = "pass",
    score: float = 0.9,
    issues: list | None = None,
    suggestions: list | None = None,
    summary: str = "Looks good.",
    extra: dict | None = None,
) -> str:
    payload: dict = {
        "verdict": verdict,
        "score": score,
        "issues": issues if issues is not None else [],
        "suggestions": suggestions if suggestions is not None else [],
        "summary": summary,
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# VerifierSummary dataclass
# ---------------------------------------------------------------------------


class TestVerifierSummary:
    def test_passed_property_true_when_verdict_pass(self):
        vs = VerifierSummary(verdict="pass", score=1.0)
        assert vs.passed is True
        assert vs.failed is False

    def test_failed_property_true_when_verdict_fail(self):
        vs = VerifierSummary(verdict="fail", score=0.0)
        assert vs.failed is True
        assert vs.passed is False

    def test_passed_false_for_partial(self):
        vs = VerifierSummary(verdict="partial", score=0.5)
        assert vs.passed is False
        assert vs.failed is False

    def test_to_dict_round_trip(self):
        vs = VerifierSummary(
            verdict="partial",
            score=0.6,
            issues=["issue1"],
            suggestions=["fix1"],
            summary="Partial pass.",
            metadata={"model": "gpt-4"},
        )
        d = vs.to_dict()
        assert d["verdict"] == "partial"
        assert d["score"] == 0.6
        assert d["issues"] == ["issue1"]
        assert d["suggestions"] == ["fix1"]
        assert d["summary"] == "Partial pass."
        assert d["metadata"] == {"model": "gpt-4"}

    def test_default_fields_are_empty(self):
        vs = VerifierSummary(verdict="pass", score=1.0)
        assert vs.issues == []
        assert vs.suggestions == []
        assert vs.summary == ""
        assert vs.metadata == {}


# ---------------------------------------------------------------------------
# build_prompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    def test_returns_system_and_user_keys(self):
        result = build_prompt(task="Do X", agent_output="I did X")
        assert "system" in result
        assert "user" in result

    def test_task_appears_in_user_prompt(self):
        result = build_prompt(task="Implement feature Y", agent_output="Here is Y")
        assert "Implement feature Y" in result["user"]

    def test_agent_output_appears_in_user_prompt(self):
        result = build_prompt(task="Do Z", agent_output="Output for Z")
        assert "Output for Z" in result["user"]

    def test_custom_criteria_appears_in_user_prompt(self):
        result = build_prompt(
            task="Do A",
            agent_output="A done",
            criteria="Must be idempotent",
        )
        assert "Must be idempotent" in result["user"]

    def test_default_criteria_used_when_none(self):
        result = build_prompt(task="Do B", agent_output="B done")
        assert "correct" in result["user"].lower() or "complete" in result["user"].lower()

    def test_extra_context_appended(self):
        result = build_prompt(
            task="Do C",
            agent_output="C done",
            extra_context="Context: production environment",
        )
        assert "production environment" in result["user"]

    def test_raises_on_empty_task(self):
        with pytest.raises(ValueError, match="task"):
            build_prompt(task="", agent_output="something")

    def test_raises_on_empty_agent_output(self):
        with pytest.raises(ValueError, match="agent_output"):
            build_prompt(task="Do something", agent_output="")

    def test_system_prompt_mentions_json(self):
        result = build_prompt(task="T", agent_output="O")
        assert "JSON" in result["system"]

    def test_system_prompt_lists_all_verdicts(self):
        result = build_prompt(task="T", agent_output="O")
        for v in VALID_VERDICTS:
            assert v in result["system"]

    def test_whitespace_stripped_from_inputs(self):
        result = build_prompt(task="  My task  ", agent_output="  My output  ")
        assert "My task" in result["user"]
        assert "My output" in result["user"]


# ---------------------------------------------------------------------------
# parse_response – happy paths
# ---------------------------------------------------------------------------


class TestParseResponseHappyPath:
    def test_parse_pass_verdict(self):
        raw = _make_raw(verdict="pass", score=1.0)
        vs = parse_response(raw)
        assert vs.verdict == "pass"
        assert vs.score == 1.0
        assert vs.passed is True

    def test_parse_fail_verdict(self):
        raw = _make_raw(verdict="fail", score=0.1, issues=["Wrong output"])
        vs = parse_response(raw)
        assert vs.verdict == "fail"
        assert vs.issues == ["Wrong output"]

    def test_parse_partial_verdict(self):
        raw = _make_raw(verdict="partial", score=0.5)
        vs = parse_response(raw)
        assert vs.verdict == "partial"
        assert vs.score == 0.5

    def test_parse_needs_review_verdict(self):
        raw = _make_raw(verdict="needs_review", score=0.7)
        vs = parse_response(raw)
        assert vs.verdict == "needs_review"

    def test_score_boundary_zero(self):
        raw = _make_raw(verdict="fail", score=0.0)
        vs = parse_response(raw)
        assert vs.score == 0.0

    def test_score_boundary_one(self):
        raw = _make_raw(verdict="pass", score=1.0)
        vs = parse_response(raw)
        assert vs.score == 1.0

    def test_issues_and_suggestions_parsed(self):
        raw = _make_raw(
            verdict="partial",
            score=0.4,
            issues=["Missing tests", "No docstring"],
            suggestions=["Add unit tests", "Add docstring"],
        )
        vs = parse_response(raw)
        assert "Missing tests" in vs.issues
        assert "No docstring" in vs.issues
        assert "Add unit tests" in vs.suggestions
        assert "Add docstring" in vs.suggestions

    def test_summary_parsed(self):
        raw = _make_raw(verdict="pass", score=0.95, summary="All criteria met.")
        vs = parse_response(raw)
        assert vs.summary == "All criteria met."

    def test_extra_keys_go_to_metadata(self):
        raw = _make_raw(verdict="pass", score=1.0, extra={"model": "gpt-4", "tokens": 123})
        vs = parse_response(raw)
        assert vs.metadata["model"] == "gpt-4"
        assert vs.metadata["tokens"] == 123

    def test_score_as_integer_is_accepted(self):
        payload = {"verdict": "pass", "score": 1, "issues": [], "suggestions": [], "summary": ""}
        vs = parse_response(json.dumps(payload))
        assert vs.score == 1.0

    def test_fenced_json_block_parsed(self):
        inner = _make_raw(verdict="pass", score=0.8)
        raw = f"```json\n{inner}\n```"
        vs = parse_response(raw)
        assert vs.verdict == "pass"

    def test_fenced_block_without_language_tag(self):
        inner = _make_raw(verdict="fail", score=0.2)
        raw = f"```\n{inner}\n```"
        vs = parse_response(raw)
        assert vs.verdict == "fail"

    def test_json_embedded_in_prose(self):
        inner = _make_raw(verdict="partial", score=0.6)
        raw = f"Here is my assessment:\n{inner}\nEnd of response."
        vs = parse_response(raw)
        assert vs.verdict == "partial"

    def test_empty_issues_and_suggestions_default(self):
        payload = {"verdict": "pass", "score": 1.0, "summary": "Great"}
        vs = parse_response(json.dumps(payload))
        assert vs.issues == []
        assert vs.suggestions == []


# ---------------------------------------------------------------------------
# parse_response – error paths
# ---------------------------------------------------------------------------


class TestParseResponseErrors:
    def test_raises_on_empty_string(self):
        with pytest.raises(ValueError, match="[Ee]mpty"):
            parse_response("")

    def test_raises_on_whitespace_only(self):
        with pytest.raises(ValueError, match="[Ee]mpty"):
            parse_response("   \n  ")

    def test_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match="[Jj][Ss][Oo][Nn]"):
            parse_response("not json at all")

    def test_raises_on_json_array_not_object(self):
        with pytest.raises(ValueError, match="object"):
            parse_response(json.dumps([1, 2, 3]))

    def test_raises_on_invalid_verdict(self):
        raw = _make_raw(verdict="unknown_verdict", score=0.5)
        with pytest.raises(ValueError, match="verdict"):
            parse_response(raw)

    def test_raises_on_missing_score(self):
        payload = {"verdict": "pass", "issues": [], "suggestions": [], "summary": ""}
        with pytest.raises(ValueError, match="score"):
            parse_response(json.dumps(payload))

    def test_raises_on_score_above_one(self):
        raw = _make_raw(verdict="pass", score=1.1)
        with pytest.raises(ValueError, match="score"):
            parse_response(raw)

    def test_raises_on_score_below_zero(self):
        raw = _make_raw(verdict="pass", score=-0.1)
        with pytest.raises(ValueError, match="score"):
            parse_response(raw)

    def test_raises_on_non_numeric_score(self):
        payload = {"verdict": "pass", "score": "high", "issues": [], "suggestions": [], "summary": ""}
        with pytest.raises(ValueError, match="score"):
            parse_response(json.dumps(payload))

    def test_raises_on_issues_not_list(self):
        payload = {"verdict": "pass", "score": 0.9, "issues": "bad", "suggestions": [], "summary": ""}
        with pytest.raises(ValueError, match="issues"):
            parse_response(json.dumps(payload))

    def test_raises_on_suggestions_not_list(self):
        payload = {"verdict": "pass", "score": 0.9, "issues": [], "suggestions": "bad", "summary": ""}
        with pytest.raises(ValueError, match="suggestions"):
            parse_response(json.dumps(payload))


# ---------------------------------------------------------------------------
# Round-trip: build_prompt → parse_response (using a mock model response)
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Simulate a full build → (mock model) → parse cycle."""

    def _mock_model(self, prompt: dict) -> str:  # noqa: ARG002
        """Pretend model that always returns a valid pass response."""
        return json.dumps(
            {
                "verdict": "pass",
                "score": 0.95,
                "issues": [],
                "suggestions": ["Consider adding more tests."],
                "summary": "The agent output fully satisfies the task requirements.",
            }
        )

    def test_full_cycle_pass(self):
        prompt = build_prompt(
            task="Write a function that adds two numbers.",
            agent_output="def add(a, b):\n    return a + b",
        )
        raw = self._mock_model(prompt)
        vs = parse_response(raw)
        assert vs.passed
        assert vs.score == 0.95
        assert vs.suggestions == ["Consider adding more tests."]

    def test_full_cycle_preserves_summary(self):
        prompt = build_prompt(task="T", agent_output="O")
        raw = self._mock_model(prompt)
        vs = parse_response(raw)
        assert "satisfies" in vs.summary
