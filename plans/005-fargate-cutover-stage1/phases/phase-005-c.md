# Phase 005-C: Pre-flight — Secrets Manager + IAM + networking validation

## Goal
Verify every external dependency Fargate Hermes needs (Neon, Bedrock, Slack tokens, etc.) is reachable from the task IAM role BEFORE flipping `desiredCount=1`, to avoid 5-minute ECS restart-loop debugging.

## Context
Fargate-day-1 failure mode is "task starts, can't read secret, crashes, restarts, crashes, restarts..." Pre-flight catches this in 30 seconds instead.

## Dependencies
- Phase 005-B complete (v8 image in ECR)
- AWS SSO active on `AgenticHub-162471567408` profile

## Scope

### Files to Create
None.

### Files to Modify
None — this is verification only.

### Explicitly Out of Scope
- Creating new secrets (if missing → STOP, escalate as separate work)
- Rotating existing secrets
- Network policy changes (if egress fails → STOP, escalate)

## Implementation Notes

1. **Inspect the existing task definition** (`aws ecs describe-task-definition --task-definition hermes-saas`) — it will tell you exactly which secret ARNs the task expects.
2. **Test each secret individually.** Don't trust IAM simulation alone; do a real `aws secretsmanager get-secret-value` from the same profile.
3. **For Neon + Bedrock**, do a connection test (psql / boto3 call) rather than just IAM allowed-yes. Network ACLs / SG egress can fail even when IAM allows.

## Acceptance Criteria
- [ ] `agentic-stack/neon/hermes-saas` secret exists, returns the `hermes_app` DSN (NOT owner — verify role string)
- [ ] `agentic-stack/hermes/slack-bot-token` exists + non-empty
- [ ] `agentic-stack/hermes/slack-app-token` exists + non-empty (required for Socket Mode)
- [ ] Optional: `agentic-stack/hermes/rooben-service-token` if used by cloud Hermes
- [ ] Task IAM role can `secretsmanager:GetSecretValue` on each of the above ARNs (verify via `aws iam simulate-principal-policy`)
- [ ] Task IAM role can `bedrock:InvokeModel` on the configured model (typically `us.anthropic.claude-sonnet-4-6`)
- [ ] Neon connectivity check: `psql "<hermes_app-dsn>" -c 'SELECT 1'` succeeds (proves egress to Neon endpoint works from your laptop's perspective; Fargate's VPC routing is separately verified by ECS Health-OK)
- [ ] Findings recorded in STATUS.md under "Adaptations log" — note any secrets that exist but have wrong values

## Verification Steps

```bash
PROFILE='AgenticHub-162471567408'

# 1. Task def
aws ecs describe-task-definition --task-definition hermes-saas --profile $PROFILE \
  --query 'taskDefinition.{family:family, taskRole:taskRoleArn, execRole:executionRoleArn, containers:containerDefinitions[*].{name:name, image:image, secrets:secrets}}'

# 2. Secrets existence + size
for s in agentic-stack/neon/hermes-saas agentic-stack/hermes/slack-bot-token agentic-stack/hermes/slack-app-token; do
  echo "--- $s ---"
  aws secretsmanager describe-secret --secret-id "$s" --profile $PROFILE \
    --query '{name:Name, lastChanged:LastChangedDate}' --output json
done

# 3. IAM simulation (replace <task-role-arn> with the actual ARN from step 1)
# aws iam simulate-principal-policy --policy-source-arn <task-role-arn> ...

# 4. Neon connectivity (from your laptop — proxies Fargate's VPC test imperfectly but useful)
/opt/homebrew/opt/libpq/bin/psql "postgresql://hermes_app:w3fdElmBnKwUOGfrvchBjyLDlj7RMMpF@ep-weathered-credit-aqq9kjyf.c-8.us-east-1.aws.neon.tech/neondb?sslmode=require" -c "SELECT 1;"
```

## Status
Not started
