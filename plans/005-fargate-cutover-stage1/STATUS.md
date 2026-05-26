# Status — Plan 005: Hermes Fargate Cutover (Stage 1)

**Status:** IN PROGRESS (Phase A queued)
**Last updated:** 2026-05-25
**Blocked by:** None — Plan 007 closed 2026-05-25 unblocking this work
**Blocks:** Plan 008 (MCPGateway production wiring) — Plan 008 dispatches after 005-G soak completes

## Phase Progress

| Phase | Title | Status | Notes |
|---|---|---|---|
| 005-A | Land + verify PR #13 on main | **In progress** | 9 commits queued on feat/plan-004-self-improvement |
| 005-B | Build + push v8 Docker image | Not started | Depends on A |
| 005-C | Pre-flight: Secrets Manager + IAM + networking | Not started | Depends on B |
| 005-D | Flip Fargate desiredCount=1; verify cold-start | Not started | Depends on C |
| 005-E | Cloud-side smoke test (Slack → Neon round-trip) | Not started | Depends on D + Blake at Slack |
| 005-F | Unload local launchd; assert single-listener invariant | Not started | Depends on E |
| 005-G | 48h soak + cutover sign-off | Not started | Calendar time, depends on F |
| 005-H | Document + open Plan 008 carry-forward | Not started | Depends on G |

## Resumption context

- Next phase: 005-A — merge PR #13 to main
- Plan 007 closed 2026-05-25 with 9 commits on the branch. Phase A is the merge gate.

## Adaptations log

(none yet — will populate per-phase as we go)
