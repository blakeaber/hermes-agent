# Phase 005-A: Land + verify PR #13 on main

## Goal
Get all Plan 004 + Plan 007 work merged to `main` so the v8 Docker image builds from a stable, CI-green code base.

## Context
The v8 image must include 9 commits currently on `feat/plan-004-self-improvement` (Plan 004-A tenant bootstrap + `_agent_default` + Plan 007 A→E in full). Building from a feature branch creates rollback ambiguity; main-tagged builds are the standard pattern.

## Dependencies
None — PR #13 already exists and has 9 commits pushed.

## Scope

### Files to Create
None.

### Files to Modify
None — this is a merge operation, not a code change.

### Explicitly Out of Scope
- New code (this phase only ships what's already on the branch)
- Squash/rebase opinions — Blake's call; either is fine for v8 build
- Closing PR #13 (the merge closes it automatically)

## Implementation Notes

1. **CI must be green** before merge. Earlier in this session PR #13 had 3 pre-existing red checks (test/asyncpg, nix-ubuntu/npmDepsHash, check-attribution). Those are unrelated to Plan 004/007 but block auto-merge. Either: get them passing, or merge admin-override with explicit note.
2. **Squash recommended** — 9 commits on the branch (tenant bootstrap → backend init → 7 Plan 007 commits). Squash to one merge commit keeps main history readable.
3. **After merge**, the v8 image build (Phase 005-B) will check out main + tag with the merge commit SHA, NOT the branch HEAD.

## Acceptance Criteria
- [ ] PR #13 CI conclusion is `success` (or red checks are documented + explicitly waived)
- [ ] PR #13 merged to `main` on `blakeaber/hermes-agent` fork
- [ ] `git fetch && git log origin-fork/main --oneline -5` shows commits including `b235c88` (007-E fix) and `1828d0d` (Plan 004-A tenant bootstrap)
- [ ] PR #13 is in `closed` / `merged` state

## Verification Steps

```bash
cd /Users/blakeaber/Documents/hermes-agent

# 1. Current PR state
gh pr view 13 --json state,mergeable,statusCheckRollup --jq '{state, mergeable, checks: [.statusCheckRollup[] | {name, conclusion}]}'

# 2. After merge:
gh pr view 13 --json state,mergedAt --jq .
git fetch origin-fork main
git log origin-fork/main --oneline -10 | head
```

## Status
Complete — 2026-05-25

### Adaptations
- The PR that landed Plan 007 was numbered **PR #13** ("Plan 004 + UAT fixes — draft for CI verification") on the fork, not the originally-assumed PR. Headers matched: `headRefOid: 57504e4`.
- Merged via `gh pr merge 13 --squash --admin` because 2 checks (`check-attribution`, `nix ubuntu`) are pre-existing OSS-upstream CI infrastructure issues unrelated to Plan 007 code. Same checks were red on PR #12 and that one merged anyway.
- Merge commit: `f5ac23b0e37fc425328dd5c237887e1a9d091e58` (2026-05-26 02:31 UTC).
- Local main fast-forward synced to the squash-merge commit. Plan 007 code (`append_raw_event`, etc.) confirmed present on main.
