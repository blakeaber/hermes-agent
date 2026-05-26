# Phase 005-F: Unload local launchd; assert single-listener invariant

## Goal
Make cloud Fargate the sole Slack listener. Eliminate the duplicate-reply state from Phase E. Keep the launchd plist on disk (renamed) for trivial rollback.

## Context
Two Hermes listeners on the same Slack socket is operationally wrong (Slack delivers each event to BOTH, resulting in duplicate replies). Phase E tolerated this temporarily; Phase F closes the loop. Local stays disabled for the duration of Plan 005's soak; rollback is `mv` + `launchctl bootstrap`.

## Dependencies
- Phase 005-E complete + green

## Scope

### Files to Create
None.

### Files to Modify
- `~/Library/LaunchAgents/ai.hermes.gateway.plist` — rename to `.plist.disabled-stage1-cutover-2026-05-25` (rollback marker)

### Explicitly Out of Scope
- Deleting the plist (rollback safety)
- Removing the `.hermes` directory (sessions, kanban.db, logs all stay for forensic + rollback)
- Killing the launchd-spawned MCP subprocesses (they exit when the gateway exits)

## Implementation Notes

1. **Bootout first, then rename.** `launchctl bootout` while the file is on disk; rename after. If you rename first, bootout fails because launchctl tries to read the plist path.
2. **Verify exactly ONE listener.** `lsof -i -P | grep ESTABLISHED.*slack` should return 0 results from your laptop (cloud listener doesn't show in your local lsof).
3. **Confirm single-reply.** Post a fresh `@Hermes` message and ensure only ONE reply arrives (not two).

## Acceptance Criteria
- [ ] `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.hermes.gateway.plist` succeeds
- [ ] `launchctl list | grep hermes` returns no rows
- [ ] `ps aux | grep hermes_cli | grep -v grep` returns no rows on the laptop
- [ ] `~/Library/LaunchAgents/ai.hermes.gateway.plist.disabled-stage1-cutover-2026-05-25` exists (renamed marker)
- [ ] After 30s, `@Hermes UAT 005-F single-listener test` returns exactly ONE reply (not two)
- [ ] CloudWatch shows the cloud Hermes received the message; local Hermes has no logs after the bootout timestamp

## Verification Steps

```bash
# 1. Bootout local
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/ai.hermes.gateway.plist
launchctl list | grep hermes && echo "STILL LOADED — STOP" || echo "OK: unloaded"

# 2. Process check
ps aux | grep hermes_cli | grep -v grep
# Expected: empty

# 3. Rename for rollback marker
mv ~/Library/LaunchAgents/ai.hermes.gateway.plist \
   ~/Library/LaunchAgents/ai.hermes.gateway.plist.disabled-stage1-cutover-2026-05-25

# 4. Send test message in Slack: @Hermes UAT 005-F single-listener test
# Count replies in Slack thread — must be exactly 1
```

## Status
Not started
