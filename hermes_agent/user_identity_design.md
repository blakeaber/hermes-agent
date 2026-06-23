# User Identity Design

## Overview

This document describes the user identity model for the Hermes agent system. It covers the canonical data model, per-user isolation guarantees, platform ID mapping strategy, and how risk-control scoping is applied on a per-user basis.

---

## 1. Data Model Fields

Each user identity record contains the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `user_id` | `string (UUID v4)` | Yes | Canonical internal identifier. Stable across all platforms and sessions. |
| `display_name` | `string` | No | Human-readable name, sourced from the originating platform. May be updated on re-auth. |
| `email` | `string \| null` | No | Verified email address, if provided by the platform. Used for notifications and account recovery. |
| `platform_ids` | `PlatformIdentity[]` | Yes | One or more platform-specific identity records (see §3). |
| `created_at` | `ISO 8601 timestamp` | Yes | UTC timestamp of first identity creation. |
| `updated_at` | `ISO 8601 timestamp` | Yes | UTC timestamp of last modification to any field. |
| `risk_profile` | `RiskProfile` | Yes | Per-user risk-control configuration (see §4). |
| `is_active` | `boolean` | Yes | Whether the user account is currently active. Inactive users are denied all agent actions. |
| `metadata` | `Record<string, unknown>` | No | Arbitrary key-value store for platform-specific or feature-flag data. Not used in access decisions. |

### 1.1 PlatformIdentity Sub-record

| Field | Type | Required | Description |
|---|---|---|---|
| `platform` | `PlatformType` | Yes | Enum identifying the originating platform (see §3). |
| `platform_user_id` | `string` | Yes | The user's ID as issued by the external platform. |
| `linked_at` | `ISO 8601 timestamp` | Yes | When this platform identity was linked to the canonical `user_id`. |
| `last_seen_at` | `ISO 8601 timestamp` | Yes | Most recent authenticated interaction from this platform identity. |
| `verified` | `boolean` | Yes | Whether the platform identity has passed verification (e.g. OAuth token exchange). |

### 1.2 RiskProfile Sub-record

See §4 for full details.

---

## 2. Per-User Isolation Contract

All agent state, conversation history, tool call logs, and stored preferences are partitioned by `user_id`. The following guarantees are enforced at the storage and runtime layers:

1. **Storage isolation** — Every persistent record (conversation turns, tool outputs, cached context) carries a `user_id` foreign key. Queries without an explicit `user_id` filter are rejected at the repository layer.
2. **Runtime isolation** — Agent execution contexts are instantiated per `user_id`. No shared mutable state exists between two concurrently running user sessions.
3. **Cross-user read prohibition** — No code path may read records belonging to `user_id` A while servicing a request authenticated as `user_id` B. Violations are treated as critical security defects.
4. **Audit trail** — Every write operation records the acting `user_id` and the authenticated `platform_user_id` that initiated the request, enabling full attribution.
5. **Deletion propagation** — A request to delete a user identity triggers cascading deletion (or anonymisation, per data-retention policy) of all records keyed to that `user_id` within 30 days.

---

## 3. Platform ID Mapping Strategy

The system supports multiple external identity providers. Each is assigned a `PlatformType` enum value.

### 3.1 Supported Platforms

| `PlatformType` | Description |
|---|---|
| `CLI` | Local terminal session authenticated via API key or device token. |
| `SLACK` | Slack workspace user, identified by Slack's `U…` user ID. |
| `WEB` | Browser-based UI authenticated via OAuth 2.0 / OIDC. |
| `API` | Direct API caller authenticated via a service account or personal access token. |
| `VOICE` | Voice interface (e.g. Alexa skill), identified by the platform's customer ID. |

### 3.2 Mapping Algorithm

1. On first contact from a platform, extract the `platform_user_id` from the verified credential.
2. Query the `platform_ids` index for an existing record matching `(platform, platform_user_id)`.
3. **Match found** → return the associated canonical `user_id`; update `last_seen_at`.
4. **No match found** → create a new `UserIdentity` record with a freshly generated `user_id`; insert a `PlatformIdentity` record; emit a `user.created` event.
5. **Account linking** — A user may explicitly link a second platform identity to an existing `user_id` (e.g. linking their Slack account to an existing Web account). This requires a verified session on the existing account and produces a new `PlatformIdentity` row pointing to the same `user_id`.

### 3.3 Collision Avoidance

- `(platform, platform_user_id)` pairs are stored with a unique index; duplicate inserts are rejected.
- Platform IDs are treated as opaque strings; no semantic parsing is performed.
- If a platform reuses a `platform_user_id` after account deletion (rare but possible), the system detects the mismatch via `linked_at` vs. platform account creation date and flags the record for manual review.

---

## 4. Risk-Control Per-User Scoping

Risk controls are evaluated per `user_id` at the start of every agent action. The `RiskProfile` record governs these controls.

### 4.1 RiskProfile Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `tier` | `'standard' \| 'elevated' \| 'restricted'` | `'standard'` | Overall risk tier. Determines which tool categories are available. |
| `rate_limit_rpm` | `integer` | `60` | Maximum agent requests per minute for this user. |
| `rate_limit_daily` | `integer` | `1000` | Maximum agent requests per calendar day (UTC). |
| `allowed_tool_categories` | `string[]` | `['read', 'write', 'search']` | Explicit allowlist of tool categories. Evaluated after tier-level defaults. |
| `denied_tool_ids` | `string[]` | `[]` | Explicit denylist of specific tool IDs, regardless of category allowlist. |
| `max_context_tokens` | `integer` | `32000` | Maximum token budget per conversation context window for this user. |
| `require_confirmation` | `boolean` | `false` | If `true`, all destructive tool calls require an explicit user confirmation step. |
| `suspension_reason` | `string \| null` | `null` | Non-null when `is_active` is `false`; human-readable reason for suspension. |

### 4.2 Evaluation Order

Risk controls are applied in the following precedence order (highest to lowest):

1. **Account active check** — If `is_active` is `false`, reject immediately with `USER_SUSPENDED`.
2. **Rate limit check** — Evaluate `rate_limit_rpm` and `rate_limit_daily` against the per-user counter store. Reject with `RATE_LIMIT_EXCEEDED` if breached.
3. **Tier-level tool gate** — Map `tier` to a set of permitted tool categories:
   - `standard`: all categories in `allowed_tool_categories`.
   - `elevated`: same as standard, plus access to `admin` category tools.
   - `restricted`: only `read` and `search` categories, regardless of `allowed_tool_categories`.
4. **Category allowlist** — Confirm the requested tool's category appears in `allowed_tool_categories` (after tier adjustment).
5. **Tool denylist** — Reject if the specific `tool_id` appears in `denied_tool_ids`.
6. **Confirmation gate** — If `require_confirmation` is `true` and the tool is tagged `destructive`, pause execution and surface a confirmation prompt to the user.

### 4.3 Risk Tier Promotion / Demotion

- Tier changes are recorded in an append-only `risk_tier_audit_log` with `user_id`, `changed_by`, `old_tier`, `new_tier`, and `reason`.
- Only users with the `risk_admin` system role may modify `tier`, `denied_tool_ids`, or `require_confirmation`.
- Automated demotion to `restricted` is triggered when a user exceeds the daily rate limit on three consecutive days.

---

## 5. Open Questions / Future Work

- **Multi-tenant scoping**: When organisation-level tenancy is introduced, `user_id` isolation will be nested within an `org_id` partition. The data model will be extended with an `org_id` field and all isolation guarantees will apply at the `(org_id, user_id)` composite key level.
- **Token-based identity**: Support for short-lived JWT-scoped identities (e.g. for CI/CD pipelines) is planned. These will map to a synthetic `user_id` with `tier: 'restricted'` and a TTL-based `is_active` flag.
- **GDPR right-to-erasure**: The 30-day deletion propagation window (§2) will be configurable per deployment region to comply with local data-retention regulations.
