"""
Channel context resolver.

A ``ChannelContextResolver`` selects or constructs the most appropriate
:class:`~hermes_agent.channel_context.models.ChannelContext` from a
collection of candidates, using ``channel_id`` as the primary resolution
key.

Typical usage
-------------
::

    resolver = ChannelContextResolver(candidates)
    ctx = resolver.resolve(channel_id="C01234567")

    # Or resolve from a raw dict payload:
    ctx = resolver.resolve_from_dict({"channel_id": "C01234567", ...})
"""

from __future__ import annotations

from typing import Dict, Any, Iterable, List, Optional

from hermes_agent.channel_context.models import ChannelContext, ChannelType


class ChannelContextResolver:
    """Resolve a :class:`ChannelContext` from a pool of candidates.

    The resolver holds an ordered list of :class:`ChannelContext` objects
    and provides lookup by ``channel_id``.  When multiple candidates share
    the same ``channel_id`` the *first* match (in insertion order) is
    returned.

    Parameters
    ----------
    candidates:
        An iterable of :class:`ChannelContext` objects that form the
        resolution pool.  Defaults to an empty pool.

    Examples
    --------
    >>> from hermes_agent.channel_context.models import ChannelContext
    >>> ctx = ChannelContext.for_slack(channel_id="C1", user_id="U1")
    >>> resolver = ChannelContextResolver([ctx])
    >>> resolver.resolve("C1") is ctx
    True
    """

    def __init__(
        self,
        candidates: Optional[Iterable[ChannelContext]] = None,
    ) -> None:
        self._candidates: List[ChannelContext] = (
            list(candidates) if candidates is not None else []
        )

    # ------------------------------------------------------------------
    # Pool management
    # ------------------------------------------------------------------

    def add(self, ctx: ChannelContext) -> None:
        """Append *ctx* to the resolution pool.

        Parameters
        ----------
        ctx:
            The :class:`ChannelContext` to add.
        """
        self._candidates.append(ctx)

    def candidates(self) -> List[ChannelContext]:
        """Return a shallow copy of the current candidate pool."""
        return list(self._candidates)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(self, channel_id: str) -> Optional[ChannelContext]:
        """Return the first candidate whose ``channel_id`` matches.

        Parameters
        ----------
        channel_id:
            The platform-specific channel identifier to look up.

        Returns
        -------
        ChannelContext or None
            The first matching :class:`ChannelContext`, or ``None`` when
            no candidate has the given *channel_id*.
        """
        for ctx in self._candidates:
            if ctx.channel_id == channel_id:
                return ctx
        return None

    def resolve_or_default(
        self,
        channel_id: str,
        default: Optional[ChannelContext] = None,
    ) -> Optional[ChannelContext]:
        """Return the first matching candidate, or *default* if none found.

        Parameters
        ----------
        channel_id:
            The platform-specific channel identifier to look up.
        default:
            Value returned when no candidate matches.  Defaults to
            ``None``.

        Returns
        -------
        ChannelContext or None
        """
        result = self.resolve(channel_id)
        return result if result is not None else default

    def resolve_from_dict(
        self, data: Dict[str, Any]
    ) -> Optional[ChannelContext]:
        """Resolve using the ``channel_id`` found inside *data*.

        If *data* contains a ``"channel_id"`` key whose value matches a
        candidate, that candidate is returned.  Otherwise a new
        :class:`ChannelContext` is constructed from *data* via
        :meth:`~hermes_agent.channel_context.models.ChannelContext.from_dict`
        and returned.

        This means callers always receive a :class:`ChannelContext` - the
        return value is never ``None`` when *data* is a valid (possibly
        empty) mapping.

        Parameters
        ----------
        data:
            A plain dictionary, typically deserialised from JSON.

        Returns
        -------
        ChannelContext
            A matched candidate or a freshly constructed context.
        """
        channel_id: Optional[str] = data.get("channel_id")
        if channel_id is not None:
            matched = self.resolve(channel_id)
            if matched is not None:
                return matched
        # Fall back to constructing a context from the raw payload.
        return ChannelContext.from_dict(data)

    def resolve_all(self, channel_id: str) -> List[ChannelContext]:
        """Return *all* candidates whose ``channel_id`` matches.

        Parameters
        ----------
        channel_id:
            The platform-specific channel identifier to look up.

        Returns
        -------
        list of ChannelContext
            All matching candidates in insertion order.  Empty list when
            none match.
        """
        return [ctx for ctx in self._candidates if ctx.channel_id == channel_id]

    def resolve_by_type(
        self,
        channel_id: str,
        channel_type: ChannelType,
    ) -> Optional[ChannelContext]:
        """Return the first candidate matching both *channel_id* and *channel_type*.

        Parameters
        ----------
        channel_id:
            The platform-specific channel identifier to look up.
        channel_type:
            The :class:`~hermes_agent.channel_context.models.ChannelType`
            that the candidate must have.

        Returns
        -------
        ChannelContext or None
        """
        for ctx in self._candidates:
            if ctx.channel_id == channel_id and ctx.channel_type is channel_type:
                return ctx
        return None
