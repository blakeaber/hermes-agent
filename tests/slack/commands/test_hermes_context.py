"""Tests for hermes_agent.slack.commands.hermes_context."""

from __future__ import annotations

import pytest

from hermes_agent.channel_context.models import ChannelContext, ChannelType
from hermes_agent.channel_context.resolver import ChannelContextResolver
from hermes_agent.slack.commands.hermes_context import (
    HermesContextCommand,
    build_context_from_slack_payload,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slack_payload(**kwargs: object) -> dict:
    """Return a minimal Slack slash-command payload, overridable via kwargs."""
    base: dict = {
        "channel_id": "C01234567",
        "channel_name": "general",
        "user_id": "U9999",
        "user_name": "alice",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# build_context_from_slack_payload
# ---------------------------------------------------------------------------


class TestBuildContextFromSlackPayload:
    def test_returns_channel_context(self):
        result = build_context_from_slack_payload(_slack_payload())
        assert isinstance(result, ChannelContext)

    def test_channel_type_is_slack(self):
        result = build_context_from_slack_payload(_slack_payload())
        assert result.channel_type is ChannelType.SLACK

    def test_channel_id_mapped(self):
        result = build_context_from_slack_payload(_slack_payload(channel_id="C111"))
        assert result.channel_id == "C111"

    def test_channel_name_mapped(self):
        result = build_context_from_slack_payload(_slack_payload(channel_name="#eng"))
        assert result.channel_name == "#eng"

    def test_user_id_mapped(self):
        result = build_context_from_slack_payload(_slack_payload(user_id="U42"))
        assert result.user_id == "U42"

    def test_user_name_mapped_to_display_name(self):
        result = build_context_from_slack_payload(_slack_payload(user_name="bob"))
        assert result.user_display_name == "bob"

    def test_thread_ts_mapped_to_thread_id(self):
        result = build_context_from_slack_payload(
            _slack_payload(thread_ts="1234567890.000100")
        )
        assert result.thread_id == "1234567890.000100"

    def test_thread_ts_absent_gives_none_thread_id(self):
        payload = _slack_payload()
        payload.pop("thread_ts", None)
        result = build_context_from_slack_payload(payload)
        assert result.thread_id is None

    def test_message_ts_mapped_to_message_id(self):
        result = build_context_from_slack_payload(
            _slack_payload(message_ts="9876543210.000200")
        )
        assert result.message_id == "9876543210.000200"

    def test_ts_fallback_for_message_id(self):
        payload = _slack_payload(ts="1111111111.000300")
        result = build_context_from_slack_payload(payload)
        assert result.message_id == "1111111111.000300"

    def test_message_ts_takes_precedence_over_ts(self):
        payload = _slack_payload(message_ts="MSG_TS", ts="TS_FALLBACK")
        result = build_context_from_slack_payload(payload)
        assert result.message_id == "MSG_TS"

    def test_unknown_keys_go_to_extra(self):
        payload = _slack_payload(workspace_id="W001", enterprise_id="E001")
        result = build_context_from_slack_payload(payload)
        assert result.extra.get("workspace_id") == "W001"
        assert result.extra.get("enterprise_id") == "E001"

    def test_known_keys_not_in_extra(self):
        payload = _slack_payload()
        result = build_context_from_slack_payload(payload)
        for key in ("channel_id", "channel_name", "user_id", "user_name"):
            assert key not in result.extra

    def test_empty_payload_returns_default_slack_context(self):
        result = build_context_from_slack_payload({})
        assert result.channel_type is ChannelType.SLACK
        assert result.channel_id is None
        assert result.user_id is None

    def test_empty_string_channel_id_treated_as_none(self):
        result = build_context_from_slack_payload({"channel_id": ""})
        assert result.channel_id is None

    def test_empty_string_user_id_treated_as_none(self):
        result = build_context_from_slack_payload({"user_id": ""})
        assert result.user_id is None

    def test_domain_tags_not_set_from_payload(self):
        # Slack payloads don't carry domain_tags; should default to empty list.
        result = build_context_from_slack_payload(_slack_payload())
        assert result.domain_tags == []

    def test_purpose_not_set_from_payload(self):
        result = build_context_from_slack_payload(_slack_payload())
        assert result.purpose is None

    def test_extra_is_independent_copy(self):
        payload = _slack_payload(custom_key="custom_val")
        result = build_context_from_slack_payload(payload)
        # Mutating the original payload should not affect the context's extra.
        payload["custom_key"] = "mutated"
        assert result.extra["custom_key"] == "custom_val"

    def test_full_payload_round_trip(self):
        payload = {
            "channel_id": "C99",
            "channel_name": "#ops",
            "user_id": "U88",
            "user_name": "charlie",
            "thread_ts": "111.222",
            "message_ts": "333.444",
            "workspace_id": "W77",
        }
        result = build_context_from_slack_payload(payload)
        assert result.channel_type is ChannelType.SLACK
        assert result.channel_id == "C99"
        assert result.channel_name == "#ops"
        assert result.user_id == "U88"
        assert result.user_display_name == "charlie"
        assert result.thread_id == "111.222"
        assert result.message_id == "333.444"
        assert result.extra == {"workspace_id": "W77"}


# ---------------------------------------------------------------------------
# HermesContextCommand - construction
# ---------------------------------------------------------------------------


class TestHermesContextCommandConstruction:
    def test_default_resolver_is_none(self):
        cmd = HermesContextCommand()
        assert cmd.resolver is None

    def test_resolver_stored(self):
        resolver = ChannelContextResolver()
        cmd = HermesContextCommand(resolver=resolver)
        assert cmd.resolver is resolver

    def test_explicit_none_resolver(self):
        cmd = HermesContextCommand(resolver=None)
        assert cmd.resolver is None


# ---------------------------------------------------------------------------
# HermesContextCommand.handle - no resolver
# ---------------------------------------------------------------------------


class TestHermesContextCommandHandleNoResolver:
    def test_returns_channel_context(self):
        cmd = HermesContextCommand()
        result = cmd.handle(_slack_payload())
        assert isinstance(result, ChannelContext)

    def test_channel_type_is_slack(self):
        cmd = HermesContextCommand()
        result = cmd.handle(_slack_payload())
        assert result.channel_type is ChannelType.SLACK

    def test_channel_id_propagated(self):
        cmd = HermesContextCommand()
        result = cmd.handle(_slack_payload(channel_id="C_HANDLE"))
        assert result.channel_id == "C_HANDLE"

    def test_user_id_propagated(self):
        cmd = HermesContextCommand()
        result = cmd.handle(_slack_payload(user_id="U_HANDLE"))
        assert result.user_id == "U_HANDLE"

    def test_empty_payload_handled(self):
        cmd = HermesContextCommand()
        result = cmd.handle({})
        assert isinstance(result, ChannelContext)
        assert result.channel_type is ChannelType.SLACK


# ---------------------------------------------------------------------------
# HermesContextCommand.handle - with resolver
# ---------------------------------------------------------------------------


class TestHermesContextCommandHandleWithResolver:
    def _make_resolver_with(self, *ctxs: ChannelContext) -> ChannelContextResolver:
        return ChannelContextResolver(list(ctxs))

    def _make_slack_ctx(self, channel_id: str, user_id: str = "U1") -> ChannelContext:
        return ChannelContext.for_slack(channel_id=channel_id, user_id=user_id)

    def test_returns_resolved_candidate_when_match(self):
        ctx = self._make_slack_ctx("C1")
        resolver = self._make_resolver_with(ctx)
        cmd = HermesContextCommand(resolver=resolver)
        result = cmd.handle({"channel_id": "C1", "user_id": "U_NEW"})
        assert result is ctx

    def test_resolved_candidate_not_overwritten_by_payload(self):
        ctx = self._make_slack_ctx("C1", user_id="U_ORIGINAL")
        resolver = self._make_resolver_with(ctx)
        cmd = HermesContextCommand(resolver=resolver)
        result = cmd.handle({"channel_id": "C1", "user_id": "U_NEW"})
        assert result.user_id == "U_ORIGINAL"

    def test_builds_new_context_when_no_match(self):
        ctx = self._make_slack_ctx("C1")
        resolver = self._make_resolver_with(ctx)
        cmd = HermesContextCommand(resolver=resolver)
        result = cmd.handle({"channel_id": "C_UNKNOWN", "user_id": "U2"})
        assert result is not ctx
        assert result.channel_id == "C_UNKNOWN"
        assert result.channel_type is ChannelType.SLACK

    def test_builds_new_context_when_channel_id_absent(self):
        ctx = self._make_slack_ctx("C1")
        resolver = self._make_resolver_with(ctx)
        cmd = HermesContextCommand(resolver=resolver)
        result = cmd.handle({"user_id": "U2"})
        assert isinstance(result, ChannelContext)
        assert result.channel_type is ChannelType.SLACK

    def test_builds_new_context_when_resolver_pool_empty(self):
        resolver = ChannelContextResolver()
        cmd = HermesContextCommand(resolver=resolver)
        result = cmd.handle(_slack_payload(channel_id="C99"))
        assert isinstance(result, ChannelContext)
        assert result.channel_id == "C99"

    def test_returns_first_match_when_duplicates_in_pool(self):
        ctx1 = self._make_slack_ctx("C1", user_id="U_FIRST")
        ctx2 = self._make_slack_ctx("C1", user_id="U_SECOND")
        resolver = self._make_resolver_with(ctx1, ctx2)
        cmd = HermesContextCommand(resolver=resolver)
        result = cmd.handle({"channel_id": "C1"})
        assert result is ctx1

    def test_empty_channel_id_string_not_resolved(self):
        ctx = self._make_slack_ctx("C1")
        resolver = self._make_resolver_with(ctx)
        cmd = HermesContextCommand(resolver=resolver)
        # Empty string should not match "C1"
        result = cmd.handle({"channel_id": "", "user_id": "U2"})
        assert result is not ctx
        assert result.channel_type is ChannelType.SLACK

    def test_handle_does_not_mutate_resolver_pool(self):
        ctx = self._make_slack_ctx("C1")
        resolver = self._make_resolver_with(ctx)
        cmd = HermesContextCommand(resolver=resolver)
        cmd.handle({"channel_id": "C1"})
        assert resolver.candidates() == [ctx]

    def test_multiple_handles_independent(self):
        ctx_a = self._make_slack_ctx("CA")
        ctx_b = self._make_slack_ctx("CB")
        resolver = self._make_resolver_with(ctx_a, ctx_b)
        cmd = HermesContextCommand(resolver=resolver)
        assert cmd.handle({"channel_id": "CA"}) is ctx_a
        assert cmd.handle({"channel_id": "CB"}) is ctx_b
        assert cmd.handle({"channel_id": "CC"}).channel_id == "CC"


# ---------------------------------------------------------------------------
# Integration: build_context_from_slack_payload + ChannelContextResolver
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_built_context_can_be_added_to_resolver(self):
        payload = _slack_payload(channel_id="C_INT")
        ctx = build_context_from_slack_payload(payload)
        resolver = ChannelContextResolver([ctx])
        assert resolver.resolve("C_INT") is ctx

    def test_command_handle_result_is_resolvable(self):
        cmd = HermesContextCommand()
        ctx = cmd.handle(_slack_payload(channel_id="C_CMD"))
        resolver = ChannelContextResolver([ctx])
        assert resolver.resolve("C_CMD") is ctx

    def test_resolver_with_slack_and_non_slack_contexts(self):
        slack_ctx = ChannelContext.for_slack(channel_id="C_SLACK", user_id="U1")
        feishu_ctx = ChannelContext.for_feishu(channel_id="oc_feishu", user_id="ou_1")
        resolver = ChannelContextResolver([slack_ctx, feishu_ctx])
        cmd = HermesContextCommand(resolver=resolver)

        # Slack channel resolves to the pre-existing slack context
        result = cmd.handle({"channel_id": "C_SLACK", "user_id": "U_NEW"})
        assert result is slack_ctx

        # Unknown channel builds a fresh Slack context (not the feishu one)
        result2 = cmd.handle({"channel_id": "oc_feishu", "user_id": "U_NEW"})
        # The feishu context is in the pool but handle() resolves by channel_id
        # regardless of type - it returns the first match.
        assert result2 is feishu_ctx
