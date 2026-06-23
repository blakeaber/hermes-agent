"""
verifier_summary.py
-------------------
Prompt-builder for the Verifier Summary step.

The verifier summary takes a completed agent turn (or a batch of turns) and
produces a concise, structured assessment that can be fed back into the
planner or surfaced to the user.

Public API
~~~~~~~~~~
- ``build_prompt(context)``  → ``str``
- ``parse_response(raw)``    → ``VerifierSummary``
- ``VerifierSummary``        – dataclass holding the parsed result
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class VerifierSummary:
    """Structured output produced by the verifier-summary prompt."""

    verdict: str
    """One of: 'pass', 'fail', 'partial', 'needs_review'."""

    score: float
    """Normalised confidence / quality score in [0.0, 1.0]."""

    issues: List[str] = field(default_factory=list)
    """List of identified problems (empty when verdict is 'pass')."""

    suggestions: List[str] = field(default_factory=list)
    """Actionable improvement suggestions."""

    summary: str = ""
    """One-paragraph human-readable summary."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary extra fields returned by the model."""

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"

    @property
    def failed(self) -> bool:
        return self.verdict == "fail"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "score": self.score,
            "issues": self.issues,
            "suggestions": self.suggestions,
            "summary": self.summary,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Valid verdicts
# ---------------------------------------------------------------------------

VALID_VERDICTS = {"pass", "fail", "partial", "needs_review"}

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = """\
You are a rigorous code and reasoning verifier.
Your job is to review the agent's work and produce a structured summary.

You MUST respond with a single JSON object that has exactly these keys:
  - "verdict"     : one of "pass", "fail", "partial", "needs_review"
  - "score"       : a float between 0.0 (worst) and 1.0 (best)
  - "issues"      : a JSON array of strings describing problems found
  - "suggestions" : a JSON array of strings with actionable improvements
  - "summary"     : a single paragraph (string) summarising your assessment

Do not include any text outside the JSON object.
"""

_USER_TEMPLATE = """\
## Task description
{task}

## Agent output
{agent_output}

## Criteria
{criteria}

Please verify the agent output against the task description and criteria,
then return your structured JSON assessment.
"""


def build_prompt(
    task: str,
    agent_output: str,
    criteria: Optional[str] = None,
    *,
    extra_context: Optional[str] = None,
) -> Dict[str, str]:
    """Build the system + user prompt pair for the verifier-summary step.

    Parameters
    ----------
    task:
        The original task or goal the agent was trying to accomplish.
    agent_output:
        The raw output / artefacts produced by the agent.
    criteria:
        Optional acceptance criteria or rubric.  When *None* a generic
        rubric is used.
    extra_context:
        Any additional context to append to the user message.

    Returns
    -------
    dict with keys ``"system"`` and ``"user"``.
    """
    if not task:
        raise ValueError("task must be a non-empty string")
    if not agent_output:
        raise ValueError("agent_output must be a non-empty string")

    resolved_criteria = criteria or (
        "- The output must fully address the task.\n"
        "- The output must be correct, complete, and free of obvious errors.\n"
        "- The output must be clear and well-structured."
    )

    user_content = _USER_TEMPLATE.format(
        task=task.strip(),
        agent_output=agent_output.strip(),
        criteria=resolved_criteria.strip(),
    )

    if extra_context:
        user_content = user_content + "\n\n## Additional context\n" + extra_context.strip()

    return {"system": _SYSTEM_TEMPLATE.strip(), "user": user_content.strip()}


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _extract_json(raw: str) -> str:
    """Return the first JSON-like substring from *raw*."""
    # Try fenced code block first
    m = _JSON_BLOCK_RE.search(raw)
    if m:
        return m.group(1).strip()

    # Fall back: find the outermost { … }
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start : end + 1]

    return raw.strip()


def parse_response(raw: str) -> VerifierSummary:
    """Parse the model's raw text response into a :class:`VerifierSummary`.

    Parameters
    ----------
    raw:
        The raw string returned by the language model.

    Returns
    -------
    :class:`VerifierSummary`

    Raises
    ------
    ValueError
        If the response cannot be parsed or contains invalid values.
    """
    if not raw or not raw.strip():
        raise ValueError("Empty response from model")

    json_str = _extract_json(raw)

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Response is not valid JSON: {exc}\nRaw snippet: {raw[:200]}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object, got {type(data).__name__}")

    # --- verdict ---
    verdict = data.get("verdict", "")
    if verdict not in VALID_VERDICTS:
        raise ValueError(
            f"Invalid verdict {verdict!r}. Must be one of {sorted(VALID_VERDICTS)}"
        )

    # --- score ---
    raw_score = data.get("score")
    if raw_score is None:
        raise ValueError("Response missing required key 'score'")
    try:
        score = float(raw_score)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"'score' must be a number, got {raw_score!r}") from exc
    if not (0.0 <= score <= 1.0):
        raise ValueError(f"'score' must be in [0.0, 1.0], got {score}")

    # --- issues ---
    issues = data.get("issues", [])
    if not isinstance(issues, list):
        raise ValueError(f"'issues' must be a list, got {type(issues).__name__}")
    issues = [str(i) for i in issues]

    # --- suggestions ---
    suggestions = data.get("suggestions", [])
    if not isinstance(suggestions, list):
        raise ValueError(f"'suggestions' must be a list, got {type(suggestions).__name__}")
    suggestions = [str(s) for s in suggestions]

    # --- summary ---
    summary = str(data.get("summary", ""))

    # --- metadata (everything else) ---
    known_keys = {"verdict", "score", "issues", "suggestions", "summary"}
    metadata = {k: v for k, v in data.items() if k not in known_keys}

    return VerifierSummary(
        verdict=verdict,
        score=score,
        issues=issues,
        suggestions=suggestions,
        summary=summary,
        metadata=metadata,
    )
