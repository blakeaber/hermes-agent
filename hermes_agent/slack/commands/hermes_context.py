"""
Slack ``/hermes-context`` command handler.

This module provides :func:`build_context_from_slack_payload` and the
:class:`HermesContextCommand` helper that together translate a raw Slack
slash-command payload dictionary into a
:class:`~hermes_agent.channel_context.models.ChannelContext` and optionally
resolve it against a pre-populated
:class:`~hermes_agent.channel_context.resolver.ChannelContextResolver`.

Typical usage
-------------
::

    from hermes_agent.slack.commands.hermes_context import HermesContextCommand

    cmd = HermesContextCommand(resolver=my_resolver)
    ctx = cmd.handle(slack_payload)

Or without a resolver::

    from hermes_agent.slack.commands.hermes_context import build_context_from_slack_payload

    ctx = build_context_from_slack_payload(slack_payload)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from hermes_agent.channel_context.models import ChannelContext, ChannelType
from hermes_agent.channel_context.resolver import ChannelContextResolver


def build_context_from_slack_payload(
    payload: Dict[str, Any],
) -> ChannelContext:
    """Construct a :class:`ChannelContext` from a Slack slash-command payload.

    The function maps the well-known Slack payload keys to the canonical
    :class:`ChannelContext` fields.  Any keys that are not explicitly mapped
    are stored verbatim in :attr:`~ChannelContext.extra`.

    Slack payload keys consumed
    ---------------------------
    ``channel_id``
        Maps to :attr:`~ChannelContext.channel_id`.
    ``channel_name``
        Maps to :attr:`~ChannelContext.channel_name`.
    ``user_id``
        Maps to :attr:`~ChannelContext.user_id`.
    ``user_name``
        Maps to :attr:`~ChannelContext.user_display_name`.
    ``thread_ts``
        Maps to :attr:`~ChannelContext.thread_id`.
    ``message_ts`` / ``ts``
        Maps to :attr:`~ChannelContext.message_id` (``message_ts`` takes
        precedence over ``ts``).

    Parameters
    ----------
    payload:
        A plain dictionary as received from the Slack Events API or
        slash-command endpoint.

    Returns
    -------
    ChannelContext
        A fully populated (where data is available) Slack channel context.
    """
    _KNOWN_KEYS = {
        "channel_id",
        "channel_name",
        "user_id",
        "user_name",
        "thread_ts",
        "message_ts",
        "ts",
    }

    channel_id: Optional[str] = payload.get("channel_id") or None
    channel_name: Optional[str] = payload.get("channel_name") or None
    user_id: Optional[str] = payload.get("user_id") or None
    user_display_name: Optional[str] = payload.get("user_name") or None
    thread_id: Optional[str] = payload.get("thread_ts") or None
    message_id: Optional[str] = (
        payload.get("message_ts") or payload.get("ts") or None
    )

    extra: Dict[str, Any] = {
        k: v for k, v in payload.items() if k not in _KNOWN_KEYS
    }

    return ChannelContext(
        channel_type=ChannelType.SLACK,
        channel_id=channel_id,
        channel_name=channel_name,
        thread_id=thread_id,
        user_id=user_id,
        user_display_name=user_display_name,
        message_id=message_id,
        extra=extra,
    )


class HermesContextCommand:
    """Slack command handler that resolves or builds a :class:`ChannelContext`.

    Parameters
    ----------
    resolver:
        An optional :class:`~hermes_agent.channel_context.resolver.ChannelContextResolver`
        used to look up a pre-existing context before constructing a new one.
        When ``None`` (the default) every call to :meth:`handle` constructs a
        fresh context from the payload.

    Examples
    --------
    >>> cmd = HermesContextCommand()
    >>> ctx = cmd.handle({"channel_id": "C1", "user_id": "U1"})
    >>> ctx.channel_type.value
    'slack'
    """

    def __init__(
        self,
        resolver: Optional[ChannelContextResolver] = None,
    ) -> None:
        self._resolver = resolver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def resolver(self) -> Optional[ChannelContextResolver]:
        """The attached :class:`ChannelContextResolver`, or ``None``."""
        return self._resolver

    def handle(self, payload: Dict[str, Any]) -> ChannelContext:
        """Process a Slack slash-command payload and return a context.

        If a :class:`ChannelContextResolver` was provided at construction time
        and the payload contains a ``channel_id`` that matches a candidate in
        the resolver pool, that candidate is returned directly.  Otherwise a
        new :class:`ChannelContext` is built from *payload* via
        :func:`build_context_from_slack_payload`.

        Parameters
        ----------
        payload:
            Raw Slack slash-command or event payload dictionary.

        Returns
        -------
        ChannelContext
            Resolved or freshly constructed context.
        """
        if self._resolver is not None:
            channel_id: Optional[str] = payload.get("channel_id") or None
            if channel_id is not None:
                matched = self._resolver.resolve(channel_id)
                if matched is not None:
                    return matched

        return build_context_from_slack_payload(payload)
