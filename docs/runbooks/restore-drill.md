# Restore drill

A backup that has never been restored is a hope, not a backup. Run this every quarter and before the first pilot. Target: a restored copy answering queries within 30 minutes, with at most 5 minutes of data lost.

## Drill

1. Note the current time as the restore point.
2. Neon console: Branches, Create branch, "from a point in time", pick the restore point. Name it `restore-drill-YYYYMMDD`. This does not touch production.
3. Copy the new branch's connection string and check it:
   ```bash
   psql "$RESTORE_URL" -c "select count(*) from users" -c "select max(created_at) from messages"
   ```
   The newest message should be within a few minutes of the restore point.
4. Point a throwaway API at it and prove the data is usable, not just present. Encrypted columns only decrypt with the right `MSG_ENC_KEY`, so this step also proves the key backup:
   ```bash
   cd apps/api
   DATABASE_URL="$RESTORE_URL" ENV=staging uv run alembic current     # same revision as prod
   DATABASE_URL="$RESTORE_URL" ENV=staging make dev                   # then GET /readyz and read one conversation
   ```
5. Write down how long steps 2 to 4 took in the drill log below.
6. Delete the branch.

## Real restore

1. Stop writes: scale `ainet-api` and `ainet-worker` to 0.
2. Create the branch from the moment just before the damage, as in the drill.
3. Check the data on the branch.
4. Set `DATABASE_URL` and `DATABASE_URL_DIRECT` to the branch, deploy, scale back up.
5. Redis holds only caches, rate limits, presence and the job queue. Flush it after a database restore so nothing points at rows that no longer exist; scheduled jobs re-enqueue from the scheduler.
6. Tell users what was lost, if anything.

## What is and is not backed up

| Data | Backup |
|---|---|
| Postgres | Neon point-in-time restore (check the retention window on the current plan) |
| Photos in R2 | Enable object versioning on the bucket |
| Redis | Not backed up, by design. It can be rebuilt. |
| Secrets | Render environment group, plus an offline copy of `MSG_ENC_KEY` and any retired keys |

## Drill log

| Date | Who | Time to restore | Problems found |
|---|---|---|---|
| | | | |
