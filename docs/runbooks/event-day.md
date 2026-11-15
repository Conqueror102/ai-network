# Event day

## The day before

1. Deploy freeze. Nothing ships after 18:00 the day before unless it fixes the event.
2. Run the load test against staging with the expected headcount ([load-test.md](load-test.md)). All thresholds green.
3. Check the event in the organizer console: status `published`, start and end times in the venue's time zone, meeting points filled in, capacity correct.
4. Open the door QR page on the device that will sit at the door. Print the static QR as a backup only if the organizer enabled it.
5. Confirm providers: OTP balance (Termii, Twilio), Resend sending domain healthy, AI provider key valid and budget (`AI_EVENT_BUDGET_USD`) set for this event.
6. Scale: API to 3 instances, worker to 2. Scale back the day after.
7. Check `/readyz` on every service and that the `outbox_lag_seconds` graph is flat near zero.

## During the event

Watch one dashboard with these four graphs: request error rate, p95 latency, `outbox_lag_seconds`, `checkins_total`.

| What you see | What it means | What to do |
|---|---|---|
| Check-ins flat while people are queueing | Door QR page is stale or offline | Reload the door page. If the venue network is down, switch the door device to mobile data. |
| Sign-ins failing | OTP provider trouble | See "People cannot sign in" in [incident.md](incident.md). |
| Matches show no reasons | AI provider slow or over budget | The feed still works. See "AI provider is down" in [incident.md](incident.md). |
| Notifications late | Outbox or worker backlog | See "Outbox is stuck" in [incident.md](incident.md). |
| One person is harassing others | Safety | Staff: `GET /v1/internal/moderation/reports`, then `POST /v1/internal/moderation/reports/{id}/action`. Every action is written to the audit log. |

Kill switches (feature flags, no deploy needed): `sponsor.surfaces.<event_id>` turns sponsored tiles off for one event. `photo.auto_approve` set to false sends new photos to manual review.

## After the event

1. The morning after, wrap-up notifications go out on their own (`connections.wrapup_sweep`). Check `jobs_total{name="connections.wrapup"}` moved.
2. Scale API and worker back down.
3. Write down anything that surprised you in the event's retro note, then turn each surprise into a ticket.
