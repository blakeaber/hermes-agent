"""Tests for hermes_agent.channel_context.resolver."""

from __future__ import annotations

import pytest

from hermes_agent.channel_context.models import ChannelContext, ChannelType
from hermes_agent.channel_context.resolver import ChannelContextResolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slack(channel_id: str, user_id: str = "U1", **kwargs) -> ChannelContext:
    return ChannelContext.for_slack(channel_id=channel_id, user_id=user_id, **kwargs)


def _feishu(channel_id: str, user_id: str = "ou_1", **kwargs) -> ChannelContext:
    return ChannelContext.for_feishu(channel_id=channel_id, user_id=user_id, **kwargs)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_empty_by_default(self):
        resolver = ChannelContextResolver()
        assert resolver.candidates() == []

    def test_accepts_iterable_of_candidates(self):
        ctx1 = _slack("C1")
        ctx2 = _slack("C2")
        resolver = ChannelContextResolver([ctx1, ctx2])
        assert resolver.candidates() == [ctx1, ctx2]

    def test_accepts_generator(self):
        ctxs = [_slack(f"C{i}") for i in range(3)]
        resolver = ChannelContextResolver(c for c in ctxs)
        assert len(resolver.candidates()) == 3

    def test_candidates_returns_copy(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        copy = resolver.candidates()
        copy.append(_slack("C2"))
        assert len(resolver.candidates()) == 1


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


class TestAdd:
    def test_add_appends_to_pool(self):
        resolver = ChannelContextResolver()
        ctx = _slack("C1")
        resolver.add(ctx)
        assert resolver.candidates() == [ctx]

    def test_add_multiple_preserves_order(self):
        resolver = ChannelContextResolver()
        ctx1 = _slack("C1")
        ctx2 = _slack("C2")
        ctx3 = _slack("C3")
        resolver.add(ctx1)
        resolver.add(ctx2)
        resolver.add(ctx3)
        assert resolver.candidates() == [ctx1, ctx2, ctx3]

    def test_add_duplicate_channel_id_allowed(self):
        resolver = ChannelContextResolver()
        ctx1 = _slack("C1", user_id="U1")
        ctx2 = _slack("C1", user_id="U2")
        resolver.add(ctx1)
        resolver.add(ctx2)
        assert len(resolver.candidates()) == 2


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------


class TestResolve:
    def test_returns_matching_candidate(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        assert resolver.resolve("C1") is ctx

    def test_returns_none_when_no_match(self):
        resolver = ChannelContextResolver([_slack("C1")])
        assert resolver.resolve("C999") is None

    def test_returns_none_on_empty_pool(self):
        resolver = ChannelContextResolver()
        assert resolver.resolve("C1") is None

    def test_returns_first_match_when_duplicates(self):
        ctx1 = _slack("C1", user_id="U1")
        ctx2 = _slack("C1", user_id="U2")
        resolver = ChannelContextResolver([ctx1, ctx2])
        assert resolver.resolve("C1") is ctx1

    def test_does_not_match_none_channel_id(self):
        ctx = ChannelContext(channel_type=ChannelType.CLI)
        resolver = ChannelContextResolver([ctx])
        # Searching for a real channel_id should not match a ctx with None
        assert resolver.resolve("C1") is None

    def test_exact_string_match(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        assert resolver.resolve("c1") is None  # case-sensitive
        assert resolver.resolve("C1") is ctx

    def test_multiple_candidates_correct_one_returned(self):
        ctx_a = _slack("CA")
        ctx_b = _slack("CB")
        ctx_c = _slack("CC")
        resolver = ChannelContextResolver([ctx_a, ctx_b, ctx_c])
        assert resolver.resolve("CB") is ctx_b

    def test_does_not_mutate_pool(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        resolver.resolve("C1")
        assert resolver.candidates() == [ctx]


# ---------------------------------------------------------------------------
# resolve_or_default
# ---------------------------------------------------------------------------


class TestResolveOrDefault:
    def test_returns_match_when_found(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        assert resolver.resolve_or_default("C1") is ctx

    def test_returns_none_default_when_not_found(self):
        resolver = ChannelContextResolver()
        assert resolver.resolve_or_default("C1") is None

    def test_returns_provided_default_when_not_found(self):
        fallback = _slack("FALLBACK")
        resolver = ChannelContextResolver()
        assert resolver.resolve_or_default("C1", default=fallback) is fallback

    def test_does_not_use_default_when_match_exists(self):
        ctx = _slack("C1")
        fallback = _slack("FALLBACK")
        resolver = ChannelContextResolver([ctx])
        assert resolver.resolve_or_default("C1", default=fallback) is ctx


# ---------------------------------------------------------------------------
# resolve_from_dict
# ---------------------------------------------------------------------------


class TestResolveFromDict:
    def test_returns_candidate_when_channel_id_matches(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        result = resolver.resolve_from_dict({"channel_id": "C1"})
        assert result is ctx

    def test_constructs_new_context_when_no_match(self):
        resolver = ChannelContextResolver()
        result = resolver.resolve_from_dict(
            {"channel_type": "slack", "channel_id": "C99", "user_id": "U1"}
        )
        assert isinstance(result, ChannelContext)
        assert result.channel_id == "C99"
        assert result.channel_type is ChannelType.SLACK

    def test_constructs_new_context_when_pool_empty(self):
        resolver = ChannelContextResolver()
        result = resolver.resolve_from_dict({"channel_type": "cli"})
        assert isinstance(result, ChannelContext)
        assert result.channel_type is ChannelType.CLI

    def test_constructs_new_context_when_channel_id_absent(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        result = resolver.resolve_from_dict({"channel_type": "email"})
        assert isinstance(result, ChannelContext)
        assert result.channel_type is ChannelType.EMAIL

    def test_empty_dict_returns_default_channel_context(self):
        resolver = ChannelContextResolver()
        result = resolver.resolve_from_dict({})
        assert isinstance(result, ChannelContext)
        assert result.channel_type is ChannelType.UNKNOWN

    def test_candidate_takes_priority_over_dict_fields(self):
        # The candidate has user_id="U_original"; the dict says user_id="U_new".
        # When the candidate is matched, the candidate object is returned as-is.
        ctx = _slack("C1", user_id="U_original")
        resolver = ChannelContextResolver([ctx])
        result = resolver.resolve_from_dict(
            {"channel_id": "C1", "user_id": "U_new"}
        )
        assert result is ctx
        assert result.user_id == "U_original"

    def test_returns_first_candidate_match(self):
        ctx1 = _slack("C1", user_id="U1")
        ctx2 = _slack("C1", user_id="U2")
        resolver = ChannelContextResolver([ctx1, ctx2])
        result = resolver.resolve_from_dict({"channel_id": "C1"})
        assert result is ctx1


# ---------------------------------------------------------------------------
# resolve_all
# ---------------------------------------------------------------------------


class TestResolveAll:
    def test_returns_empty_list_when_no_match(self):
        resolver = ChannelContextResolver([_slack("C1")])
        assert resolver.resolve_all("C999") == []

    def test_returns_empty_list_on_empty_pool(self):
        resolver = ChannelContextResolver()
        assert resolver.resolve_all("C1") == []

    def test_returns_single_match(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        assert resolver.resolve_all("C1") == [ctx]

    def test_returns_all_matches_in_order(self):
        ctx1 = _slack("C1", user_id="U1")
        ctx2 = _slack("C2", user_id="U2")
        ctx3 = _slack("C1", user_id="U3")
        resolver = ChannelContextResolver([ctx1, ctx2, ctx3])
        result = resolver.resolve_all("C1")
        assert result == [ctx1, ctx3]

    def test_returns_copy_not_internal_list(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        result = resolver.resolve_all("C1")
        result.append(_slack("C2"))
        # Pool should be unchanged
        assert len(resolver.candidates()) == 1


# ---------------------------------------------------------------------------
# resolve_by_type
# ---------------------------------------------------------------------------


class TestResolveByType:
    def test_returns_match_on_id_and_type(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        assert resolver.resolve_by_type("C1", ChannelType.SLACK) is ctx

    def test_returns_none_when_id_matches_but_type_differs(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        assert resolver.resolve_by_type("C1", ChannelType.FEISHU) is None

    def test_returns_none_when_type_matches_but_id_differs(self):
        ctx = _slack("C1")
        resolver = ChannelContextResolver([ctx])
        assert resolver.resolve_by_type("C999", ChannelType.SLACK) is None

    def test_returns_none_on_empty_pool(self):
        resolver = ChannelContextResolver()
        assert resolver.resolve_by_type("C1", ChannelType.SLACK) is None

    def test_returns_first_match_among_same_id_and_type(self):
        ctx1 = _slack("C1", user_id="U1")
        ctx2 = _slack("C1", user_id="U2")
        resolver = ChannelContextResolver([ctx1, ctx2])
        assert resolver.resolve_by_type("C1", ChannelType.SLACK) is ctx1

    def test_disambiguates_by_type_when_same_channel_id(self):
        slack_ctx = _slack("SHARED")
        feishu_ctx = _feishu("SHARED")
        resolver = ChannelContextResolver([slack_ctx, feishu_ctx])
        assert resolver.resolve_by_type("SHARED", ChannelType.SLACK) is slack_ctx
        assert resolver.resolve_by_type("SHARED", ChannelType.FEISHU) is feishu_ctx

    def test_cli_context_resolved_by_type(self):
        cli_ctx = ChannelContext.for_cli(user_id="local")
        # CLI contexts have no channel_id; resolve_by_type with None channel_id
        # should not match a non-None search key.
        resolver = ChannelContextResolver([cli_ctx])
        assert resolver.resolve_by_type("C1", ChannelType.CLI) is None


# ---------------------------------------------------------------------------
# Integration: mixed pool
# ---------------------------------------------------------------------------


class TestMixedPool:
    def test_resolve_across_platform_types(self):
        slack_ctx = _slack("C1")
        feishu_ctx = _feishu("oc_abc")
        cli_ctx = ChannelContext.for_cli(user_id="local")
        resolver = ChannelContextResolver([slack_ctx, feishu_ctx, cli_ctx])

        assert resolver.resolve("C1") is slack_ctx
        assert resolver.resolve("oc_abc") is feishu_ctx
        assert resolver.resolve("nonexistent") is None

    def test_add_then_resolve(self):
        resolver = ChannelContextResolver()
        ctx = _slack("C1")
        resolver.add(ctx)
        assert resolver.resolve("C1") is ctx

    def test_resolve_from_dict_falls_back_to_construction_for_unknown_id(self):
        resolver = ChannelContextResolver([_slack("C1")])
        result = resolver.resolve_from_dict(
            {"channel_type": "feishu", "channel_id": "oc_new", "user_id": "ou_x"}
        )
        assert isinstance(result, ChannelContext)
        assert result.channel_type is ChannelType.FEISHU
        assert result.channel_id == "oc_new"
