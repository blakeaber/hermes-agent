# Phase 005-G: 48-hour soak + cutover sign-off

## Goal
Run cloud Fargate Hermes for 48 hours of real daily-driver use to prove the clock-skew bug class (Bedrock 403, websocket zombies) is genuinely gone and Plan 005 is a real cutover, not a demo.

## Context
The whole reason Plan 005 exists is the recurring class of failures that hit local launchd Hermes (clock skew → Bedrock 403, laptop sleep → DNS dropouts, etc.). A 5-minute "it works" test doesn't prove those are gone. 48 hours under real use does.

## Dependencies
- Phase 005-F complete (single-listener invariant holds)

## Scope

### Files to Create
None.

### Files to Modify
None — calendar-time observation.

### Explicitly Out of Scope
- Adding additional features during the soak (freeze)
- Scaling experiments
- Cost optimization

## Implementation Notes

1. **Set CloudWatch billing alarm at $50/mo** before soak starts. Expected steady-state is $30–40 for 24/7 t-tier — alarm catches runaway costs early.
2. **Set CloudWatch alarm on `Essential container exited` event count > 0** for the soak window.
3. **Set CloudWatch log group retention to 90 days** (default is never; that gets expensive).
4. **Watch for the `feedback-triage-nightly` cron firing** at its scheduled UTC time — proves the cron path works in Fargate too (Plan 006-A territory but the cron itself lives in Hermes config).
5. **Daily-driver use, not synthetic load.** The soak's point is "would Blake actually live with this." If you don't use it, you're not testing it.

## Acceptance Criteria
- [ ] 48 hours elapse with `aws ecs describe-services` showing `runningCount=1, desiredCount=1, pendingCount=0` throughout
- [ ] Zero task restarts caused by container exit (`Essential container exited` event count = 0)
- [ ] At least 10 Slack interactions completed end-to-end during the soak (counted via `messages` rows in Neon)
- [ ] P95 reply latency ≤ 30s for the 10 interactions (CloudWatch + Neon `created_at` deltas)
- [ ] At least one cron firing of `feedback-triage-nightly` completes without Bedrock 403 (CloudWatch grep)
- [ ] Zero `signature expired` errors in CloudWatch across the 48h window
- [ ] Average task RSS < 400 MB across the soak (memory_monitor heartbeats)
- [ ] CloudWatch billing alarm at $50/mo configured (verify via `aws cloudwatch describe-alarms`)
- [ ] CloudWatch log retention set to 90 days on `/ecs/hermes-saas`

## Verification Steps

```bash
PROFILE='AgenticHub-162471567408'

# At soak start + at 24h + at 48h:
aws ecs describe-services --cluster agentic-stack --services hermes \
  --query 'services[0].{desired:desiredCount, running:runningCount, pending:pendingCount, events:events[0:3]}' \
  --profile $PROFILE

# Restart count
aws logs filter-log-events --log-group-name /ecs/hermes-saas \
  --filter-pattern '"Essential container exited"' --start-time $(date -v-48H +%s)000 \
  --profile $PROFILE | jq '.events | length'

# Signature expired count
aws logs filter-log-events --log-group-name /ecs/hermes-saas \
  --filter-pattern '"signature expired"' --start-time $(date -v-48H +%s)000 \
  --profile $PROFILE | jq '.events | length'

# Neon interaction count
/opt/homebrew/opt/libpq/bin/psql "<hermes_app-dsn>" -c "
SELECT set_config('app.tenant_id','ac85d33a-c466-4d4c-9747-0a8d69efbe6f',false);
SELECT COUNT(*) FROM messages WHERE created_at > NOW() - INTERVAL '48 hours' AND role='user';
"
```

## Status
Not started
