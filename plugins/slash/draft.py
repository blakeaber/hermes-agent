"""/draft slash command — Atlas-aware draft skeleton (Plan 030-A).

This is the **first phase** of Plan 030 ("Atlas-aware draft skill" — R2 CP3).
030-A ships the slash-command skeleton + recipient resolution only; the
Atlas context fetch (030-B) and the actual LLM draft generation (030-C)
are stubbed and surface as ``TODO`` markers in the returned message so
the wiring is visible end-to-end without burning model spend.

Usage::

    /draft sarah@example.com follow-up on the term sheet

The first whitespace-delimited token is the recipient. Two shapes are
supported in v1:

* **Email** — matches ``RFC5322`` lite (``local@domain.tld``). Returned
  in the reply as the resolved recipient and used as the lookup key
  for the future Atlas / Gmail context fetch (030-B).
* **Slack handle** — ``@somebody``. v1 surfaces it as-is in the reply;
  Slack ``users.lookupByEmail`` resolution lands in 030-C when the
  Slack client is wired through. For now we strip the leading ``@``
  and pass the bare handle through so 030-C can drop in the lookup
  without changing the public command surface.

The remaining tokens form the intent string. We preserve quoting
loosely by joining on a single space — Slack's slash-command transport
already strips outer quotes, but if Blake double-quotes the intent we
strip a single matched pair so the surface ``/draft a@b.com "context"``
behaves like ``/draft a@b.com context``.

Auth: the Hermes gateway's ``SLACK_ALLOWED_USERS`` gate is enforced at
the platform layer (gateway/platforms/slack.py) — by the time this
handler runs we already trust the caller. We do **not** re-check the
allowlist here.

The handler is sync (``fn(raw_args: str) -> str``) per the
``PluginContext.register_command`` contract that the Plan 020-E
``/resume`` and ``/skip`` handlers established.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Recipient parsing
# ---------------------------------------------------------------------------

# Email regex is intentionally permissive — Slack already normalizes
# auto-linked emails, and overly strict patterns reject valid plus-tags
# and subdomains. Mirrors the shape used by hermes_storage email mapping.
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

# A Slack handle is ``@`` followed by 1+ word chars (letters, digits,
# underscore, dot, dash). We do **not** accept bare-word handles in v1 —
# the leading ``@`` is the disambiguator.
_HANDLE_RE = re.compile(r"^@([a-zA-Z0-9._\-]+)$")


@dataclass(frozen=True)
class Recipient:
    """Parsed recipient.

    ``kind`` is one of ``"email"``, ``"handle"``, ``"unresolved"``. The
    ``value`` is the raw token (with leading ``@`` stripped for handles
    so callers don't need to special-case it). ``display`` is what we
    surface in the Slack reply — for emails we synthesize a friendly
    first-name display, for handles we keep ``@handle``, for unresolved
    we echo the raw token so Blake sees exactly what he typed.
    """

    kind: str
    value: str
    display: str


def _friendly_name_from_email(email: str) -> str:
    """Derive a display name from the email local-part.

    ``sarah.connor+pe@example.com`` → ``Sarah``. Strips plus-tags and
    dot-separated segments after the first. Falls back to the raw
    local-part title-cased if no separator is present.
    """
    local = email.split("@", 1)[0]
    # Drop plus-tag (``user+tag`` → ``user``)
    local = local.split("+", 1)[0]
    # First dot-segment is conventionally the first name
    first = local.split(".", 1)[0]
    if not first:
        return email
    return first[:1].upper() + first[1:].lower()


def _parse_recipient(token: str) -> Recipient:
    """Classify the first arg as email / handle / unresolved."""
    if _EMAIL_RE.match(token):
        return Recipient(
            kind="email",
            value=token,
            display=_friendly_name_from_email(token),
        )
    handle_match = _HANDLE_RE.match(token)
    if handle_match:
        bare = handle_match.group(1)
        return Recipient(kind="handle", value=bare, display=f"@{bare}")
    return Recipient(kind="unresolved", value=token, display=token)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftArgs:
    """Parsed ``/draft`` invocation."""

    recipient: Recipient
    intent: str


def _strip_matched_quotes(s: str) -> str:
    """Strip a single matched pair of leading/trailing ASCII quotes."""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _parse_args(raw_args: str) -> Optional[DraftArgs]:
    """Split into (recipient_token, intent_string).

    Returns ``None`` when there's nothing to parse — the handler turns
    that into a usage reply.
    """
    if not raw_args or not raw_args.strip():
        return None
    parts = raw_args.strip().split(None, 1)
    recipient_token = parts[0]
    intent = parts[1].strip() if len(parts) > 1 else ""
    intent = _strip_matched_quotes(intent)
    recipient = _parse_recipient(recipient_token)
    return DraftArgs(recipient=recipient, intent=intent)


# ---------------------------------------------------------------------------
# Stub reply composition
# ---------------------------------------------------------------------------


def _usage() -> str:
    return (
        "Usage: /draft <recipient> <context>\n"
        'Example: /draft sarah@example.com "follow-up on the term sheet"\n'
        "Recipient may be an email (``user@host``) or Slack handle (``@somebody``)."
    )


def _compose_stub_reply(args: DraftArgs) -> str:
    """Render the 030-A stub message.

    Format intentionally matches the orchestrator's expected acceptance
    test in the master plan: a header line ("Drafting message to <display>
    (<recipient value>)") followed by two TODO markers pointing at the
    next two phases (030-B context lookup, 030-C draft generation).
    """
    if args.recipient.kind == "email":
        header = (
            f"Drafting message to {args.recipient.display} "
            f"({args.recipient.value})"
        )
    elif args.recipient.kind == "handle":
        header = f"Drafting message to {args.recipient.display}"
    else:
        header = f"Drafting message to {args.recipient.display} (unresolved)"

    intent_line = (
        f"Intent: {args.intent}" if args.intent else "Intent: (none provided)"
    )
    return (
        f"{header}\n"
        f"{intent_line}\n"
        "[context lookup: TODO 030-B]\n"
        "[draft generation: TODO 030-C]"
    )


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


def handle_draft(raw_args: str) -> str:
    """``/draft <recipient> <context>`` — Plan 030-A skeleton.

    Returns a stub message acknowledging the recipient + intent. Atlas
    context fetch and LLM draft generation are deferred to 030-B/030-C;
    this phase exists to lock in the public command surface and the
    recipient-resolution contract.
    """
    args = _parse_args(raw_args)
    if args is None:
        return _usage()
    logger.info(
        "draft.invoked recipient_kind=%s recipient_value=%s intent_len=%d",
        args.recipient.kind,
        args.recipient.value,
        len(args.intent),
    )
    return _compose_stub_reply(args)
