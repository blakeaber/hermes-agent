"""
Tests for hermes_storage.user_store.UserStore
"""

from __future__ import annotations

import pytest

from hermes_agent.user_identity import UserIdentity
from hermes_storage.user_store import UserStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_identity(name: str = "Alice", email: str = "alice@example.com") -> UserIdentity:
    return UserIdentity(name=name, email=email)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestUserStoreConstruction:
    def test_starts_empty(self):
        store = UserStore()
        assert store.all() == {}

    def test_all_returns_dict(self):
        store = UserStore()
        result = store.all()
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestUserStoreSave:
    def test_save_stores_identity(self):
        store = UserStore()
        uid = _make_identity()
        store.save("alice", uid)
        assert store.get("alice") == uid

    def test_save_overwrites_existing(self):
        store = UserStore()
        uid1 = _make_identity(name="Alice v1")
        uid2 = _make_identity(name="Alice v2")
        store.save("alice", uid1)
        store.save("alice", uid2)
        assert store.get("alice") == uid2

    def test_save_multiple_users(self):
        store = UserStore()
        uid_a = _make_identity(name="Alice", email="alice@example.com")
        uid_b = _make_identity(name="Bob", email="bob@example.com")
        store.save("alice", uid_a)
        store.save("bob", uid_b)
        assert store.get("alice") == uid_a
        assert store.get("bob") == uid_b

    def test_save_returns_none(self):
        store = UserStore()
        result = store.save("alice", _make_identity())
        assert result is None


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------


class TestUserStoreGet:
    def test_get_returns_stored_identity(self):
        store = UserStore()
        uid = _make_identity()
        store.save("alice", uid)
        assert store.get("alice") is uid

    def test_get_returns_none_for_missing_key(self):
        store = UserStore()
        assert store.get("nonexistent") is None

    def test_get_does_not_mutate_store(self):
        store = UserStore()
        uid = _make_identity()
        store.save("alice", uid)
        store.get("alice")
        assert store.get("alice") == uid


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


class TestUserStoreDelete:
    def test_delete_existing_key_returns_true(self):
        store = UserStore()
        store.save("alice", _make_identity())
        result = store.delete("alice")
        assert result is True

    def test_delete_removes_entry(self):
        store = UserStore()
        store.save("alice", _make_identity())
        store.delete("alice")
        assert store.get("alice") is None

    def test_delete_missing_key_returns_false(self):
        store = UserStore()
        result = store.delete("nonexistent")
        assert result is False

    def test_delete_does_not_affect_other_keys(self):
        store = UserStore()
        uid_a = _make_identity(name="Alice", email="alice@example.com")
        uid_b = _make_identity(name="Bob", email="bob@example.com")
        store.save("alice", uid_a)
        store.save("bob", uid_b)
        store.delete("alice")
        assert store.get("bob") == uid_b

    def test_delete_twice_returns_false_second_time(self):
        store = UserStore()
        store.save("alice", _make_identity())
        store.delete("alice")
        assert store.delete("alice") is False


# ---------------------------------------------------------------------------
# all
# ---------------------------------------------------------------------------


class TestUserStoreAll:
    def test_all_returns_all_entries(self):
        store = UserStore()
        uid_a = _make_identity(name="Alice", email="alice@example.com")
        uid_b = _make_identity(name="Bob", email="bob@example.com")
        store.save("alice", uid_a)
        store.save("bob", uid_b)
        result = store.all()
        assert result == {"alice": uid_a, "bob": uid_b}

    def test_all_returns_shallow_copy(self):
        store = UserStore()
        uid = _make_identity()
        store.save("alice", uid)
        snapshot = store.all()
        # Mutating the returned dict must not affect the store
        snapshot["extra"] = _make_identity(name="Extra", email="extra@example.com")
        assert "extra" not in store.all()

    def test_all_reflects_deletions(self):
        store = UserStore()
        store.save("alice", _make_identity())
        store.delete("alice")
        assert store.all() == {}

    def test_all_reflects_overwrites(self):
        store = UserStore()
        uid1 = _make_identity(name="Alice v1")
        uid2 = _make_identity(name="Alice v2")
        store.save("alice", uid1)
        store.save("alice", uid2)
        assert store.all() == {"alice": uid2}

    def test_all_empty_store(self):
        store = UserStore()
        assert store.all() == {}


# ---------------------------------------------------------------------------
# Integration: combined operations
# ---------------------------------------------------------------------------


class TestUserStoreIntegration:
    def test_save_get_delete_cycle(self):
        store = UserStore()
        uid = _make_identity()
        store.save("u1", uid)
        assert store.get("u1") == uid
        assert store.delete("u1") is True
        assert store.get("u1") is None

    def test_independent_stores_do_not_share_state(self):
        store_a = UserStore()
        store_b = UserStore()
        uid = _make_identity()
        store_a.save("alice", uid)
        assert store_b.get("alice") is None

    def test_user_identity_values_are_preserved(self):
        store = UserStore()
        uid = UserIdentity(name="Specific Name", email="specific@domain.org")
        store.save("specific", uid)
        retrieved = store.get("specific")
        assert retrieved is not None
        assert retrieved.name == "Specific Name"
        assert retrieved.email == "specific@domain.org"
