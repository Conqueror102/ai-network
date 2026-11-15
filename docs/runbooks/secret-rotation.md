# Secret rotation

Rotate on a leak, when someone with access leaves, and every quarter. All secrets live in the Render environment group `ainet-prod`. Never paste a secret into chat, a ticket or a commit.

## JWT signing secret (no forced sign-out)

The API accepts tokens signed with either `JWT_SECRET` or `JWT_SECRET_NEXT` and tells them apart by key id.

1. Generate a new secret: `openssl rand -base64 48`.
2. Set `JWT_SECRET_NEXT` to it. Deploy. Both keys now verify; the old one still signs.
3. Move it: set `JWT_SECRET` to the new value, `JWT_KID` to the value `JWT_KID_NEXT` had, and remove `JWT_SECRET_NEXT`. Deploy.
4. Access tokens live 15 minutes, so 15 minutes after step 3 nothing signed with the old secret is valid.

On a confirmed leak skip the overlap: replace `JWT_SECRET` at once. Everyone refreshes their session on the next request.

## Message encryption key (`MSG_ENC_KEY`)

Chat messages, private notes and shared contact details are encrypted with this key. Each stored value starts with the id of the key that wrote it, so old rows stay readable after a rotation as long as the old key is still configured.

1. Generate: `openssl rand -hex 32`.
2. Add the current key to `MSG_ENC_OLD_KEYS` under its current id, for example `{"m1":"<current hex>"}`.
3. Set `MSG_ENC_KEY` to the new key and `MSG_ENC_KID` to a new id (`m2`). Deploy.
4. New writes use `m2`; rows written with `m1` still decrypt. Keep `m1` in `MSG_ENC_OLD_KEYS` until no row starts with `m1:` (messages are deleted after 24 months).

Losing this key means losing every message. Keep an offline copy of every key that still has rows.

## OTP pepper (`OTP_PEPPER`)

Changing it invalidates codes that are in flight (at most 10 minutes of them). Replace and deploy.

## Provider keys

| Secret | Where to rotate | Notes |
|---|---|---|
| `BACHS_API_KEY`, `BACHS_WEBHOOK_SECRET` | Bachs dashboard | `BACHS_WEBHOOK_SECRET` accepts a comma-separated list, so set `new,old`, deploy, then drop `old`. |
| AI provider keys | Provider console | Create the new key, deploy, then revoke the old one. |
| `TERMII_API_KEY`, `TWILIO_*` | Provider console | Same order: create, deploy, revoke. |
| `RESEND_API_KEY` | Resend dashboard | Same. |
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Cloudflare R2 | Same. |
| `VAPID_PRIVATE_KEY` | Regenerate the pair | Existing push subscriptions stop working; clients re-subscribe on next open. Rotate only on a leak. |
| `METRICS_TOKEN` | Generate a new token | Update the scraper at the same time. |
| Database password | Neon console | Update `DATABASE_URL` and `DATABASE_URL_DIRECT`, deploy. |

## After any rotation

Check `/readyz`, sign in once, send one message, and confirm the Sentry error rate did not move.
