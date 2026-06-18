# Phase 006-C: Linear Issue Enrichment

## Goal
Inject provenance metadata into every Linear issue Hermes creates — workflow ID, plan reference, dependency list, and a `hermes-generated` label — so Blake can read a Linear card and understand exactly which Hermes workflow produced it.

## Context
From Slack ts=1779051268: "I wish there was more context, visibility into dependencies, description of 'projects' that issues apply to, and other metadata associated with the Hermes workflows that generate issues in Linear. I can't understand, edit, comment on or do much in Linear with the current information."

The enrichment is a config-layer change at the Linear issue creation call site. No new Linear API permissions are needed — `description` and `labels` are standard fields.

## Dependencies
Phase 006-A must be Complete — this phase calls `EventLogger().get_or_create_workflow_id()` to embed the workflow ID in the issue description.

## Scope

### Files to Modify
- `tools/linear_tools.py` **OR** the MCP wrapper in `model_tools.py` (resolve Q-6.3 first) — inject provenance block into `description` and add `hermes-generated` label at issue creation
- `tools/workflow_events.py` — add `log_linear_issue_created(workflow_id, issue_id, issue_url)` helper

### Explicitly Out of Scope
- Retroactive enrichment of existing Linear issues — forward-only
- Bidirectional sync (Linear → Hermes updates) — future plan
- Auto-creating the `hermes-generated` label — create it manually in Linear once

## Implementation Notes

**Resolve Q-6.3 first:** Check if Linear is MCP-only:
```bash
python3 -c "import yaml; c=yaml.safe_load(open('/Users/blakeaber/.hermes/config.yaml')); print(list(c.get('mcp_servers',{}).keys()))"
```
If `linear` is in the MCP server list, the enrichment hook goes in `model_tools.py` around the MCP tool call, not in `tools/linear_tools.py`.

**Description template** (prepend to any existing description):
```
---
🤖 Created by Hermes
Workflow: wf-{workflow_id}
Plan: {plan_ref or "ad-hoc"}
Dependencies: {comma-separated issue IDs or "none"}
---

{original description if any}
```

**Getting workflow context:** Call `EventLogger().get_or_create_workflow_id(session_id=current_session_id)` in the issue creation path. If no session is active, use `"ad-hoc"`.

**Labels:** Add `hermes-generated` label ID. Fetch the label ID once via Linear API and hardcode it in the config, or look it up at runtime via `linear.teams[0].labels`.

## Acceptance Criteria
- [ ] Linear issue created by Hermes has `description` starting with the Hermes provenance block (workflow ID, plan ref, dependencies)
- [ ] `hermes-generated` label is applied to the issue on creation
- [ ] `workflow_events` table contains a `linear_issue_created` event with the Linear issue URL in `metadata`
- [ ] Falls back gracefully: if no active workflow context, description shows `Workflow: ad-hoc` (no crash)
  - Source: Slack ts=1779051268 (#product-feedback)

## Verification Steps
```bash
# 1. Resolve Q-6.3: find Linear integration point
grep -r "linear\|Linear" ~/Documents/hermes-agent/tools/ 2>/dev/null | grep -v ".pyc" | head -20

# 2. Trigger a Linear issue creation
# [manual] Ask Hermes: "Create a Linear issue for implementing the event log"

# 3. Check Linear
# [manual] Open the created issue in Linear — verify provenance block in description

# 4. Check event log
sqlite3 ~/.hermes/observability/events.db \
  "SELECT event_type, metadata FROM workflow_events WHERE event_type='linear_issue_created' ORDER BY ts DESC LIMIT 1;"
# Expected: linear_issue_created | {"issue_id": "...", "issue_url": "https://linear.app/..."}
```

## Status
Not started

## Bug Log
| # | Description | Status |
|---|-------------|--------|
