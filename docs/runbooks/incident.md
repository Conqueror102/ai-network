# Incident response

## First five minutes

1. Say "I have it" in the team channel so two people do not debug in parallel.
2. Look, do not guess: Render dashboard (deploys, instance health), Sentry (new errors), Grafana (error rate, p95, outbox lag).
3. If a deploy went out in the last hour and errors started with it, roll back first (Render: service, Deploys, Rollback) and investigate afterwards. A migration that already ran stays; every migration in this repo is written to be backward compatible with the previous release for exactly this reason.
4. Find the failing request's `request_id` (it is in every error response and log line) and search logs for it.

Severity: **SEV1** people cannot sign in, check in or chat during a live event. **SEV2** a feature is degraded (no match reasons, late notifications). **SEV3** everything else.

## People cannot sign in

Alert: `OtpSendFailing`.

1. Logs: search `otp_send_failed`. The `provider` field says which sender is failing.
2. The API already falls back from the primary to the secondary sender for each code. If both fail, check balances and status pages.
3. To swap the order without a deploy, set `OTP_PRIMARY` and `OTP_FALLBACK` in the Render environment group and restart the API.
4. If sign-in works but people report "too many attempts", they hit the toll-fraud caps (3 codes per number per 10 minutes, 10 per IP per hour). A shared venue Wi-Fi can exhaust the per-IP cap: ask people to use mobile data, do not raise the cap during an incident.

## Outbox is stuck

Alert: `OutboxStuck`. Symptoms: notifications, realtime updates and match recomputes stop, while requests still succeed.

1. Is the worker running? Render: `ainet-worker` should be live and its log should show jobs finishing.
2. Find the row at the head of the queue:
   ```sql
   SELECT id, topic, attempts, last_error, created_at
   FROM outbox_events WHERE processed_at IS NULL ORDER BY available_at LIMIT 20;
   ```
3. One poisoned row with `attempts` climbing: read `last_error`, fix the handler, deploy. Rows stop retrying after 10 attempts and stay in the table for inspection, so nothing is lost.
4. Many rows, no errors: the worker is under-provisioned. Scale `ainet-worker` up.

## AI provider is down

Alert: `AiFailing`.

The product is built to keep working: the feed falls back to template reasons, wave notes are held for review instead of sent unscreened, the wingman answers "unavailable". Nothing needs to be switched off.

1. Check the provider's status page and `ai_calls` for the failing task:
   ```sql
   SELECT task, outcome, count(*) FROM ai_calls
   WHERE created_at > now() - interval '15 minutes' GROUP BY 1, 2 ORDER BY 3 DESC;
   ```
2. `outcome = 'budget'` means the event or daily budget is spent, not an outage. Raise `AI_EVENT_BUDGET_USD` only with the owner's agreement.
3. To move a task to another model or provider, change the task's chain in the AI routing setting and restart. No code change is needed.

## Database trouble

1. `/readyz` reports `db: fail`: check Neon status and the connection count. The API uses the pooled URL; only Alembic uses the direct one.
2. Slow queries: Neon console, Monitoring, or `pg_stat_statements`. Look for a missing index before adding hardware.
3. Data was damaged or deleted: stop writes (scale API to 0), then follow [restore-drill.md](restore-drill.md) with the time just before the damage.

## A payment went wrong

1. Every provider webhook is stored in `webhook_events` with its raw payload. Find it by the provider's event id.
2. `payments.status = 'mismatch'` means the amount or currency did not match the invoice. Nothing was marked paid. Check with the provider before touching it.
3. Money is only ever recorded by adding rows to `ledger_entries` (the table refuses updates and deletes). To correct a mistake, staff use `mark-paid` or `refund`, which add the compensating entries and write to the audit log.

## Afterwards

Within two working days write a short review: what happened, how it was noticed, what fixed it, what will stop it happening again. No blame.
