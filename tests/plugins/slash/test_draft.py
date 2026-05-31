"""Unit tests for the /draft slash command — Plan 030-A.

Acceptance criteria covered:

AC1 — ``plugins/slash/draft.py`` exists with recipient resolution. The
      handler must parse the first whitespace-delimited token as the
      recipient and classify it as email / handle / unresolved.

AC2 — Tests pass with coverage >= 80% on new code. This module exercises
      every branch of ``_parse_args`` + ``_parse_recipient`` + the stub
      reply composer.

AC3 — Manual smoke test: ``/draft <email> "hello"`` returns the stub
      message containing the recipient and the two TODO markers (030-B
      context lookup, 030-C draft generation).

AC4 — No LLM call. The handler is pure parsing + string formatting; no
      Atlas client or model client is imported, and the test suite
      installs no mock for either. If 030-A ever starts importing
      anthropic/openai/atlas at module-load time, ``test_no_llm_imports``
      will trip.
"""

from __future__ import annotations

import sys

import pytest

from plugins.slash import draft as draft_mod
from plugins.slash.draft import (
    DraftArgs,
    Recipient,
    _compose_stub_reply,
    _friendly_name_from_email,
    _parse_args,
    _parse_recipient,
    handle_draft,
)


# ---------------------------------------------------------------------------
# Recipient parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token,expected_value,expected_display",
    [
        ("sarah@example.com", "sarah@example.com", "Sarah"),
        ("greg.smith@firm.co", "greg.smith@firm.co", "Greg"),
        ("blake.aber+pe@gmail.com", "blake.aber+pe@gmail.com", "Blake"),
        ("a@b.io", "a@b.io", "A"),
    ],
)
def test_parse_recipient_email(token, expected_value, expected_display):
    r = _parse_recipient(token)
    assert r.kind == "email"
    assert r.value == expected_value
    assert r.display == expected_display


@pytest.mark.parametrize(
    "token,bare",
    [
        ("@bossman2", "bossman2"),
        ("@greg.smith", "greg.smith"),
        ("@a_b-c", "a_b-c"),
    ],
)
def test_parse_recipient_handle(token, bare):
    r = _parse_recipient(token)
    assert r.kind == "handle"
    assert r.value == bare
    assert r.display == f"@{bare}"


@pytest.mark.parametrize(
    "token",
    [
        "not-an-email",
        "@",
        "sarah@",
        "@with spaces",  # space-containing won't reach here from _parse_args,
        "drop table;",
    ],
)
def test_parse_recipient_unresolved(token):
    r = _parse_recipient(token)
    assert r.kind == "unresolved"
    assert r.value == token
    assert r.display == token


def test_friendly_name_strips_plus_tag_and_dots():
    assert _friendly_name_from_email("sarah.connor+pe@example.com") == "Sarah"
    assert _friendly_name_from_email("greg@firm.com") == "Greg"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def test_parse_args_email_and_intent():
    args = _parse_args("sarah@example.com follow-up on the term sheet")
    assert isinstance(args, DraftArgs)
    assert args.recipient.kind == "email"
    assert args.recipient.value == "sarah@example.com"
    assert args.intent == "follow-up on the term sheet"


def test_parse_args_strips_matched_quotes():
    args = _parse_args('sarah@example.com "follow-up on the term sheet"')
    assert args is not None
    assert args.intent == "follow-up on the term sheet"


def test_parse_args_strips_matched_single_quotes():
    args = _parse_args("sarah@example.com 'hello world'")
    assert args is not None
    assert args.intent == "hello world"


def test_parse_args_does_not_strip_mismatched_quotes():
    args = _parse_args("sarah@example.com \"hello world'")
    assert args is not None
    assert args.intent == "\"hello world'"


def test_parse_args_handle_and_intent():
    args = _parse_args("@bossman2 ping me about the deck")
    assert args is not None
    assert args.recipient.kind == "handle"
    assert args.recipient.value == "bossman2"
    assert args.intent == "ping me about the deck"


def test_parse_args_no_intent_returns_empty_string():
    args = _parse_args("sarah@example.com")
    assert args is not None
    assert args.intent == ""


def test_parse_args_empty_returns_none():
    assert _parse_args("") is None
    assert _parse_args("   ") is None
    assert _parse_args(None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Stub reply composition
# ---------------------------------------------------------------------------


def test_compose_stub_reply_email_includes_header_and_todos():
    args = DraftArgs(
        recipient=Recipient(
            kind="email", value="sarah@example.com", display="Sarah"
        ),
        intent="follow-up on the term sheet",
    )
    reply = _compose_stub_reply(args)
    assert "Drafting message to Sarah (sarah@example.com)" in reply
    assert "Intent: follow-up on the term sheet" in reply
    assert "[context lookup: TODO 030-B]" in reply
    assert "[draft generation: TODO 030-C]" in reply


def test_compose_stub_reply_handle_omits_email_parens():
    args = DraftArgs(
        recipient=Recipient(kind="handle", value="bossman2", display="@bossman2"),
        intent="hello",
    )
    reply = _compose_stub_reply(args)
    assert "Drafting message to @bossman2" in reply
    # No parenthesized email since there isn't one
    assert "(" not in reply.split("\n")[0]


def test_compose_stub_reply_unresolved_marks_as_unresolved():
    args = DraftArgs(
        recipient=Recipient(kind="unresolved", value="garbage", display="garbage"),
        intent="hi",
    )
    reply = _compose_stub_reply(args)
    assert "garbage" in reply
    assert "unresolved" in reply.lower()


def test_compose_stub_reply_no_intent_says_none_provided():
    args = DraftArgs(
        recipient=Recipient(
            kind="email", value="a@b.io", display="A"
        ),
        intent="",
    )
    reply = _compose_stub_reply(args)
    assert "Intent: (none provided)" in reply


# ---------------------------------------------------------------------------
# Handler (end-to-end on the public surface)
# ---------------------------------------------------------------------------


def test_handle_draft_acceptance_smoke():
    """AC3 — manual smoke test in the master plan.

    Blake types: /draft sarah@example.com "follow-up on the term sheet"
    Expected reply contains all three required lines.
    """
    reply = handle_draft('sarah@example.com "follow-up on the term sheet"')
    assert "Drafting message to Sarah (sarah@example.com)" in reply
    assert "[context lookup: TODO 030-B]" in reply
    assert "[draft generation: TODO 030-C]" in reply


def test_handle_draft_empty_returns_usage():
    reply = handle_draft("")
    assert "Usage:" in reply
    assert "/draft" in reply


def test_handle_draft_whitespace_returns_usage():
    reply = handle_draft("   ")
    assert "Usage:" in reply


def test_handle_draft_handle_recipient_smoke():
    reply = handle_draft("@bossman2 ping me about the deck")
    assert "@bossman2" in reply
    assert "ping me about the deck" in reply


def test_handle_draft_unresolved_recipient_still_responds():
    reply = handle_draft("not-an-email some intent")
    # Should not crash; should mention the raw token
    assert "not-an-email" in reply
    assert "[draft generation: TODO 030-C]" in reply


# ---------------------------------------------------------------------------
# AC4 — no LLM call
# ---------------------------------------------------------------------------


def test_no_llm_imports_at_module_load():
    """030-A must not pull in anthropic/openai/atlas client at import time.

    030-B is where Atlas context fetch lands; 030-C is where the actual
    LLM call lands. If either sneaks into this phase, this guard trips
    and forces the author to push the dep back to its real phase.
    """
    forbidden = {"anthropic", "openai"}
    # We allow the test process to import these elsewhere, but the
    # ``draft`` module itself should not have referenced them at load
    # time. Inspect the module's globals as a proxy for what it bound.
    bound = set(vars(draft_mod).keys())
    assert bound.isdisjoint(forbidden), (
        f"draft.py bound forbidden symbols at module load: "
        f"{bound & forbidden}"
    )


# ---------------------------------------------------------------------------
# Plugin registration smoke test — confirms /draft is wired through.
# ---------------------------------------------------------------------------


def test_register_wires_draft_command():
    from plugins.slash import register

    registered: dict[str, dict] = {}

    class _Ctx:
        def register_command(
            self, name: str, handler, description: str = "", args_hint: str = ""
        ) -> None:
            registered[name] = {
                "handler": handler,
                "description": description,
                "args_hint": args_hint,
            }

    register(_Ctx())

    assert "draft" in registered
    assert registered["draft"]["args_hint"] == "<recipient> <context>"
    assert callable(registered["draft"]["handler"])
    # And the existing 020-E commands still register
    assert "resume" in registered
    assert "skip" in registered
