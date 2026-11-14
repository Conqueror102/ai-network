#!/bin/sh
# Starts the process for $ROLE. Migrations run as the platform's pre-deploy step.
set -e
case "${ROLE:-api}" in
  api)       exec uvicorn app.entrypoints.api:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*' ;;
  ws)        exec uvicorn app.entrypoints.ws:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*' ;;
  worker)    exec arq app.entrypoints.worker.WorkerSettings ;;
  scheduler) exec arq app.entrypoints.scheduler.SchedulerSettings ;;
  *) echo "unknown ROLE: $ROLE" >&2; exit 1 ;;
esac
