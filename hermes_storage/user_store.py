"""
In-memory store for UserIdentity objects.

Provides a simple CRUD interface keyed by an arbitrary ``user_id`` string.
This module intentionally has no I/O side-effects; persistence is the
responsibility of the caller.
"""

from __future__ import annotations

from typing import Dict, Optional

from hermes_agent.user_identity import UserIdentity


class UserStore:
    """Thread-unsafe in-memory mapping of ``user_id`` → :class:`UserIdentity`.

    Parameters
    ----------
    None

    Examples
    --------
    >>> store = UserStore()
    >>> uid = UserIdentity(name="Alice", email="alice@example.com")
    >>> store.save("alice", uid)
    >>> store.get("alice")
    UserIdentity(name='Alice', email='alice@example.com')
    """

    def __init__(self) -> None:
        self._data: Dict[str, UserIdentity] = {}

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save(self, user_id: str, identity: UserIdentity) -> None:
        """Insert or overwrite the identity for *user_id*.

        Parameters
        ----------
        user_id:
            Arbitrary non-empty string key that identifies the user.
        identity:
            A :class:`~hermes_agent.user_identity.UserIdentity` instance to
            store.
        """
        self._data[user_id] = identity

    def delete(self, user_id: str) -> bool:
        """Remove the entry for *user_id*.

        Parameters
        ----------
        user_id:
            Key to remove.

        Returns
        -------
        bool
            ``True`` if the key existed and was removed, ``False`` if it was
            not present.
        """
        if user_id in self._data:
            del self._data[user_id]
            return True
        return False

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, user_id: str) -> Optional[UserIdentity]:
        """Return the :class:`UserIdentity` for *user_id*, or ``None``.

        Parameters
        ----------
        user_id:
            Key to look up.
        """
        return self._data.get(user_id)

    def all(self) -> Dict[str, UserIdentity]:
        """Return a shallow copy of the entire store.

        Returns
        -------
        dict[str, UserIdentity]
            Mapping of every stored ``user_id`` to its
            :class:`UserIdentity`.  Mutations to the returned dict do not
            affect the store.
        """
        return dict(self._data)
