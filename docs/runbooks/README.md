# Runbooks

Short, step-by-step guides for the people on call. Each one assumes the stack in `docs/spec/11-backend-architecture.md`: API, worker and scheduler on Render, Postgres on Neon, Redis on Upstash, files on Cloudflare R2.

| Runbook | Use it when |
|---|---|
| [event-day.md](event-day.md) | The day before and the day of a live event |
| [incident.md](incident.md) | Something is broken or slow in production |
| [secret-rotation.md](secret-rotation.md) | A secret leaked, someone left, or the quarterly rotation is due |
| [restore-drill.md](restore-drill.md) | Quarterly, and before the first pilot: prove a backup can be restored |
| [load-test.md](load-test.md) | Before each event: prove staging holds the expected crowd |

Alert rules live in `infra/monitoring/alerts.yml`. Each alert links to the section here that handles it.
