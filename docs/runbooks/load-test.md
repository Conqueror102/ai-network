# Load test

Run before every event against **staging**, never production. The script is `infra/k6/event_day.js`.

## Steps

1. Seed staging with the expected headcount (staging uses the fake OTP sender, so the seed script can sign people in):
   ```bash
   cd apps/api
   make seed n=500
   ```
   Note the event id it prints, and make sure a worker is running so profiles get embedded and feeds built.
2. Mint tokens for those attendees right before the run (they last 15 minutes; set `ACCESS_TTL_S=3600` on staging for longer runs):
   ```bash
   uv run python -m scripts.loadtest_tokens <event_id> > ../../infra/k6/tokens.json
   ```
3. Run:
   ```bash
   k6 run -e BASE_URL=https://<staging-api-host> infra/k6/event_day.js
   ```
4. Delete `infra/k6/tokens.json` afterwards. It is git-ignored, and it is a file full of credentials.

## Pass criteria

- Fewer than 0.5% server errors.
- Reads: p95 under 300 ms, p99 under 800 ms. Writes: p95 under 500 ms, p99 under 1.2 s.
- `outbox_lag_seconds` stays under 30 during the run and returns to zero within two minutes after it.
- No instance restarts, database connections below 80% of the pool.

Answers with status 429 are expected: per-user rate limits are part of the design and the script counts them as healthy.

## If it fails

Read the slowest route from `http_request_duration_seconds` by `route`, then look at that query's plan. Add the index or fix the query, and rerun. Scale out only when the queries are already good.
