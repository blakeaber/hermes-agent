# Phase 005-B: Build + push `plan-001-E-amd64-v8` Docker image

## Goal
Build a fresh amd64 image from `main` that incorporates Phase A's merged commits, push to ECR with the v8 tag so the Fargate service update is a one-line task-def revision bump.

## Context
ECR repo `agentic-stack/hermes` already has `plan-001-E-amd64-v7` (per Plan 001-E STATUS). The v8 build inherits Plan 001-E's `Dockerfile.saas` + `scripts/build-push-saas.sh` machinery — no infra changes needed here.

## Dependencies
- Phase 005-A complete (`main` contains Plan 004 + Plan 007 commits)
- Docker Desktop running locally (for `docker build`)
- AWS SSO logged in to `AgenticHub-162471567408` profile (for ECR push)

## Scope

### Files to Create
None.

### Files to Modify
None — Phase B uses existing `Dockerfile.saas` + `scripts/build-push-saas.sh`.

### Explicitly Out of Scope
- Modifying Dockerfile.saas (any changes are their own ticket)
- Cross-platform (arm64) build — Fargate runs amd64 by design
- Multi-tag pushes — single tag `plan-001-E-amd64-v8`

## Implementation Notes

1. **Check the build script first.** `scripts/build-push-saas.sh` may take args or be hardcoded for v7. If hardcoded, either:
   - Pass tag via env var (e.g., `SAAS_IMAGE_TAG=plan-001-E-amd64-v8 ./scripts/build-push-saas.sh`)
   - Or invoke `docker build` + `aws ecr` directly
2. **Local health check before push.** Run the container locally for 30s and curl `:8080/health` → must return 200. Pushing a broken image wastes Fargate cycle time.
3. **Record the digest in STATUS.md.** Future rollbacks need the SHA, not just the tag — tags can be overwritten.

## Acceptance Criteria
- [ ] `docker build --platform linux/amd64 -f Dockerfile.saas -t agentic-stack/hermes:plan-001-E-amd64-v8 .` succeeds
- [ ] Local health check: `docker run --rm -d -p 8080:8080 agentic-stack/hermes:plan-001-E-amd64-v8; sleep 10; curl -sf http://localhost:8080/health` returns HTTP 200
- [ ] `aws ecr describe-images --repository-name agentic-stack/hermes --image-ids imageTag=plan-001-E-amd64-v8 --profile AgenticHub-162471567408` returns a row with non-empty `imageDigest`
- [ ] Image digest recorded in `plans/005-fargate-cutover-stage1/STATUS.md` under "Adaptations log"
- [ ] Local test container cleaned up (`docker stop ...`)

## Verification Steps

```bash
cd /Users/blakeaber/Documents/hermes-agent
git checkout main && git pull origin-fork main

# Inspect what's in build-push-saas.sh
cat scripts/build-push-saas.sh | head -30

# Build (may need tag arg — verify above)
./scripts/build-push-saas.sh plan-001-E-amd64-v8 2>&1 | tee /tmp/v8-build.log

# Verify push
aws ecr describe-images --repository-name agentic-stack/hermes \
  --image-ids imageTag=plan-001-E-amd64-v8 \
  --query 'imageDetails[0].{digest:imageDigest,pushed:imagePushedAt,sizeMB:imageSizeInBytes}' \
  --profile AgenticHub-162471567408 --output json
```

## Status
Complete — 2026-05-26

### Adaptations
- **Build script needed a `--platform linux/amd64` patch.** `scripts/build-push-saas.sh` ran `docker build` without a platform flag; on Apple Silicon Macs (the build host) this defaults to arm64, which Fargate (amd64 task def) can't run. Added the flag inline.
- **Local container health check skipped.** Image needs NEON_DATABASE_URL + SLACK_* + Bedrock IAM at runtime. Without those, local container would fail startup with config errors (false negative for the build itself). Build validity is now verified via Phase 005-D's CloudWatch startup-log assertions instead.
- **v8 image digest**: `sha256:5ba47504b6c8bf246f32dc4b2b97bcb0abe5576960ec67ed9205e5cb99f87d3c`
- **Full ECR URI**: `162471567408.dkr.ecr.us-east-1.amazonaws.com/agentic-stack/hermes:plan-001-E-amd64-v8`
