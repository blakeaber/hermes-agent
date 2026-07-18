"""Tests for hermes_agent.channel_context.models."""

from __future__ import annotations

import pytest

from hermes_agent.channel_context.models import ChannelContext, ChannelType


# ---------------------------------------------------------------------------
# ChannelType enum
# ---------------------------------------------------------------------------


class TestChannelType:
    def test_known_values(self):
        assert ChannelType("slack") is ChannelType.SLACK
        assert ChannelType("feishu") is ChannelType.FEISHU
        assert ChannelType("email") is ChannelType.EMAIL
        assert ChannelType("api") is ChannelType.API
        assert ChannelType("cli") is ChannelType.CLI
        assert ChannelType("unknown") is ChannelType.UNKNOWN

    def test_is_str_subclass(self):
        # ChannelType inherits from str so it can be used directly as a
        # JSON-serialisable value.
        assert isinstance(ChannelType.SLACK, str)
        assert ChannelType.SLACK == "slack"


# ---------------------------------------------------------------------------
# ChannelContext defaults
# ---------------------------------------------------------------------------


class TestChannelContextDefaults:
    def test_default_channel_type_is_unknown(self):
        ctx = ChannelContext()
        assert ctx.channel_type is ChannelType.UNKNOWN

    def test_optional_fields_default_to_none(self):
        ctx = ChannelContext()
        assert ctx.channel_id is None
        assert ctx.channel_name is None
        assert ctx.thread_id is None
        assert ctx.user_id is None
        assert ctx.user_display_name is None
        assert ctx.message_id is None
        assert ctx.purpose is None

    def test_domain_tags_defaults_to_empty_list(self):
        ctx = ChannelContext()
        assert ctx.domain_tags == []

    def test_domain_tags_not_shared_between_instances(self):
        a = ChannelContext()
        b = ChannelContext()
        a.domain_tags.append("eng")
        assert "eng" not in b.domain_tags

    def test_extra_defaults_to_empty_dict(self):
        ctx = ChannelContext()
        assert ctx.extra == {}

    def test_extra_is_not_shared_between_instances(self):
        a = ChannelContext()
        b = ChannelContext()
        a.extra["key"] = "value"
        assert "key" not in b.extra


# ---------------------------------------------------------------------------
# ChannelContext construction
# ---------------------------------------------------------------------------


class TestChannelContextConstruction:
    def test_explicit_fields(self):
        ctx = ChannelContext(
            channel_type=ChannelType.SLACK,
            channel_id="C01234567",
            channel_name="#general",
            thread_id="T0001",
            user_id="U9999",
            user_display_name="Alice",
            message_id="M42",
            domain_tags=["engineering", "oncall"],
            purpose="Engineering on-call channel",
            extra={"workspace": "W001"},
        )
        assert ctx.channel_type is ChannelType.SLACK
        assert ctx.channel_id == "C01234567"
        assert ctx.channel_name == "#general"
        assert ctx.thread_id == "T0001"
        assert ctx.user_id == "U9999"
        assert ctx.user_display_name == "Alice"
        assert ctx.message_id == "M42"
        assert ctx.domain_tags == ["engineering", "oncall"]
        assert ctx.purpose == "Engineering on-call channel"
        assert ctx.extra == {"workspace": "W001"}


# ---------------------------------------------------------------------------
# Convenience constructors
# ---------------------------------------------------------------------------


class TestForSlack:
    def test_sets_channel_type(self):
        ctx = ChannelContext.for_slack(channel_id="C1", user_id="U1")
        assert ctx.channel_type is ChannelType.SLACK

    def test_required_fields(self):
        ctx = ChannelContext.for_slack(channel_id="C1", user_id="U1")
        assert ctx.channel_id == "C1"
        assert ctx.user_id == "U1"

    def test_optional_thread(self):
        ctx = ChannelContext.for_slack(channel_id="C1", user_id="U1", thread_id="TS123")
        assert ctx.thread_id == "TS123"

    def test_channel_name_accepted(self):
        ctx = ChannelContext.for_slack(channel_id="C1", user_id="U1", channel_name="#eng")
        assert ctx.channel_name == "#eng"

    def test_channel_name_defaults_to_none(self):
        ctx = ChannelContext.for_slack(channel_id="C1", user_id="U1")
        assert ctx.channel_name is None

    def test_domain_tags_accepted(self):
        ctx = ChannelContext.for_slack(
            channel_id="C1", user_id="U1", domain_tags=["eng", "ops"]
        )
        assert ctx.domain_tags == ["eng", "ops"]

    def test_domain_tags_defaults_to_empty_list(self):
        ctx = ChannelContext.for_slack(channel_id="C1", user_id="U1")
        assert ctx.domain_tags == []

    def test_purpose_accepted(self):
        ctx = ChannelContext.for_slack(
            channel_id="C1", user_id="U1", purpose="Engineering discussions"
        )
        assert ctx.purpose == "Engineering discussions"

    def test_purpose_defaults_to_none(self):
        ctx = ChannelContext.for_slack(channel_id="C1", user_id="U1")
        assert ctx.purpose is None

    def test_extra_kwargs_stored(self):
        ctx = ChannelContext.for_slack(channel_id="C1", user_id="U1", workspace="W1")
        assert ctx.extra == {"workspace": "W1"}

    def test_missing_required_raises(self):
        with pytest.raises(TypeError):
            ChannelContext.for_slack(user_id="U1")  # channel_id missing


class TestForFeishu:
    def test_sets_channel_type(self):
        ctx = ChannelContext.for_feishu(channel_id="oc_abc", user_id="ou_xyz")
        assert ctx.channel_type is ChannelType.FEISHU

    def test_required_fields(self):
        ctx = ChannelContext.for_feishu(channel_id="oc_abc", user_id="ou_xyz")
        assert ctx.channel_id == "oc_abc"
        assert ctx.user_id == "ou_xyz"

    def test_optional_thread(self):
        ctx = ChannelContext.for_feishu(
            channel_id="oc_abc", user_id="ou_xyz", thread_id="thread_001"
        )
        assert ctx.thread_id == "thread_001"

    def test_channel_name_accepted(self):
        ctx = ChannelContext.for_feishu(
            channel_id="oc_abc", user_id="ou_xyz", channel_name="engineering"
        )
        assert ctx.channel_name == "engineering"

    def test_channel_name_defaults_to_none(self):
        ctx = ChannelContext.for_feishu(channel_id="oc_abc", user_id="ou_xyz")
        assert ctx.channel_name is None

    def test_domain_tags_accepted(self):
        ctx = ChannelContext.for_feishu(
            channel_id="oc_abc", user_id="ou_xyz", domain_tags=["backend"]
        )
        assert ctx.domain_tags == ["backend"]

    def test_domain_tags_defaults_to_empty_list(self):
        ctx = ChannelContext.for_feishu(channel_id="oc_abc", user_id="ou_xyz")
        assert ctx.domain_tags == []

    def test_purpose_accepted(self):
        ctx = ChannelContext.for_feishu(
            channel_id="oc_abc", user_id="ou_xyz", purpose="Backend team chat"
        )
        assert ctx.purpose == "Backend team chat"

    def test_purpose_defaults_to_none(self):
        ctx = ChannelContext.for_feishu(channel_id="oc_abc", user_id="ou_xyz")
        assert ctx.purpose is None

    def test_extra_kwargs_stored(self):
        ctx = ChannelContext.for_feishu(
            channel_id="oc_abc", user_id="ou_xyz", app_id="cli_app"
        )
        assert ctx.extra == {"app_id": "cli_app"}


class TestForCli:
    def test_sets_channel_type(self):
        ctx = ChannelContext.for_cli()
        assert ctx.channel_type is ChannelType.CLI

    def test_user_id_optional(self):
        ctx = ChannelContext.for_cli()
        assert ctx.user_id is None

    def test_user_id_accepted(self):
        ctx = ChannelContext.for_cli(user_id="local_user")
        assert ctx.user_id == "local_user"

    def test_domain_tags_accepted(self):
        ctx = ChannelContext.for_cli(domain_tags=["local", "dev"])
        assert ctx.domain_tags == ["local", "dev"]

    def test_domain_tags_defaults_to_empty_list(self):
        ctx = ChannelContext.for_cli()
        assert ctx.domain_tags == []

    def test_purpose_accepted(self):
        ctx = ChannelContext.for_cli(purpose="Local development")
        assert ctx.purpose == "Local development"

    def test_purpose_defaults_to_none(self):
        ctx = ChannelContext.for_cli()
        assert ctx.purpose is None

    def test_extra_kwargs_stored(self):
        ctx = ChannelContext.for_cli(profile="default")
        assert ctx.extra == {"profile": "default"}


# ---------------------------------------------------------------------------
# is_threaded
# ---------------------------------------------------------------------------


class TestIsThreaded:
    def test_false_when_no_thread_id(self):
        ctx = ChannelContext()
        assert ctx.is_threaded() is False

    def test_true_when_thread_id_set(self):
        ctx = ChannelContext(thread_id="T001")
        assert ctx.is_threaded() is True

    def test_false_when_thread_id_is_none_explicitly(self):
        ctx = ChannelContext(thread_id=None)
        assert ctx.is_threaded() is False


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestToDict:
    def test_returns_dict(self):
        ctx = ChannelContext()
        assert isinstance(ctx.to_dict(), dict)

    def test_channel_type_serialised_as_string(self):
        ctx = ChannelContext(channel_type=ChannelType.SLACK)
        d = ctx.to_dict()
        assert d["channel_type"] == "slack"
        assert isinstance(d["channel_type"], str)

    def test_all_keys_present(self):
        ctx = ChannelContext()
        d = ctx.to_dict()
        expected_keys = {
            "channel_type",
            "channel_id",
            "channel_name",
            "thread_id",
            "user_id",
            "user_display_name",
            "message_id",
            "domain_tags",
            "purpose",
            "extra",
        }
        assert set(d.keys()) == expected_keys

    def test_none_values_preserved(self):
        ctx = ChannelContext()
        d = ctx.to_dict()
        assert d["channel_id"] is None
        assert d["channel_name"] is None
        assert d["thread_id"] is None
        assert d["purpose"] is None

    def test_extra_is_copy(self):
        ctx = ChannelContext(extra={"k": "v"})
        d = ctx.to_dict()
        d["extra"]["k"] = "mutated"
        assert ctx.extra["k"] == "v"

    def test_domain_tags_is_copy(self):
        ctx = ChannelContext(domain_tags=["eng"])
        d = ctx.to_dict()
        d["domain_tags"].append("ops")
        assert ctx.domain_tags == ["eng"]

    def test_domain_tags_serialised_as_list(self):
        ctx = ChannelContext(domain_tags=["a", "b"])
        d = ctx.to_dict()
        assert d["domain_tags"] == ["a", "b"]
        assert isinstance(d["domain_tags"], list)

    def test_full_round_trip_values(self):
        ctx = ChannelContext(
            channel_type=ChannelType.FEISHU,
            channel_id="oc_abc",
            channel_name="engineering",
            thread_id="t1",
            user_id="u1",
            user_display_name="Bob",
            message_id="m1",
            domain_tags=["backend", "infra"],
            purpose="Backend infrastructure discussions",
            extra={"app": "x"},
        )
        d = ctx.to_dict()
        assert d == {
            "channel_type": "feishu",
            "channel_id": "oc_abc",
            "channel_name": "engineering",
            "thread_id": "t1",
            "user_id": "u1",
            "user_display_name": "Bob",
            "message_id": "m1",
            "domain_tags": ["backend", "infra"],
            "purpose": "Backend infrastructure discussions",
            "extra": {"app": "x"},
        }


# ---------------------------------------------------------------------------
# from_dict
# ---------------------------------------------------------------------------


class TestFromDict:
    def test_round_trip(self):
        original = ChannelContext(
            channel_type=ChannelType.SLACK,
            channel_id="C1",
            channel_name="#general",
            thread_id="T1",
            user_id="U1",
            user_display_name="Alice",
            message_id="M1",
            domain_tags=["eng"],
            purpose="General engineering",
            extra={"ws": "W1"},
        )
        restored = ChannelContext.from_dict(original.to_dict())
        assert restored.channel_type is ChannelType.SLACK
        assert restored.channel_id == "C1"
        assert restored.channel_name == "#general"
        assert restored.thread_id == "T1"
        assert restored.user_id == "U1"
        assert restored.user_display_name == "Alice"
        assert restored.message_id == "M1"
        assert restored.domain_tags == ["eng"]
        assert restored.purpose == "General engineering"
        assert restored.extra == {"ws": "W1"}

    def test_unknown_channel_type_becomes_unknown(self):
        ctx = ChannelContext.from_dict({"channel_type": "carrier_pigeon"})
        assert ctx.channel_type is ChannelType.UNKNOWN

    def test_missing_channel_type_defaults_to_unknown(self):
        ctx = ChannelContext.from_dict({})
        assert ctx.channel_type is ChannelType.UNKNOWN

    def test_missing_optional_fields_default_to_none(self):
        ctx = ChannelContext.from_dict({"channel_type": "api"})
        assert ctx.channel_id is None
        assert ctx.channel_name is None
        assert ctx.thread_id is None
        assert ctx.user_id is None
        assert ctx.user_display_name is None
        assert ctx.message_id is None
        assert ctx.purpose is None

    def test_missing_domain_tags_defaults_to_empty_list(self):
        ctx = ChannelContext.from_dict({})
        assert ctx.domain_tags == []

    def test_none_domain_tags_treated_as_empty(self):
        ctx = ChannelContext.from_dict({"domain_tags": None})
        assert ctx.domain_tags == []

    def test_domain_tags_round_trip(self):
        ctx = ChannelContext.from_dict({"domain_tags": ["a", "b"]})
        assert ctx.domain_tags == ["a", "b"]

    def test_missing_extra_defaults_to_empty_dict(self):
        ctx = ChannelContext.from_dict({})
        assert ctx.extra == {}

    def test_none_extra_treated_as_empty(self):
        ctx = ChannelContext.from_dict({"extra": None})
        assert ctx.extra == {}

    def test_unknown_top_level_keys_ignored(self):
        # Forward-compatibility: extra keys in the payload must not raise.
        ctx = ChannelContext.from_dict(
            {"channel_type": "cli", "future_field": "some_value"}
        )
        assert ctx.channel_type is ChannelType.CLI

    def test_all_channel_types_round_trip(self):
        for ct in ChannelType:
            ctx = ChannelContext(channel_type=ct)
            restored = ChannelContext.from_dict(ctx.to_dict())
            assert restored.channel_type is ct
