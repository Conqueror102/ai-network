// Event-day load test (docs/spec/09 §5, docs/spec/11 §12).
//
//   cd apps/api && uv run python -m scripts.loadtest_tokens <event_id> > ../../infra/k6/tokens.json
//   k6 run -e BASE_URL=https://api.staging.example.com infra/k6/event_day.js
//
// Models the busiest ten minutes of a 500-person event: people open the app after
// check-in, read their matches, wave, chat and poll notifications. Run it against
// staging only. Tokens expire after 15 minutes, so mint them right before the run.
import http from "k6/http";
import { check, sleep } from "k6";
import { SharedArray } from "k6/data";
import { Rate } from "k6/metrics";

const data = JSON.parse(open("./tokens.json"));
const users = new SharedArray("users", () => data.users);
const BASE = `${__ENV.BASE_URL || "http://localhost:8000"}/v1`;
const EVENT = data.event_id;
const serverErrors = new Rate("server_errors");

export const options = {
  scenarios: {
    browse: {
      executor: "ramping-vus",
      exec: "browse",
      stages: [
        { duration: "1m", target: 100 },
        { duration: "5m", target: 300 },
        { duration: "2m", target: 300 },
        { duration: "1m", target: 0 },
      ],
    },
    connect: {
      executor: "constant-arrival-rate",
      exec: "connect",
      rate: 5, // waves per second across the room
      timeUnit: "1s",
      duration: "8m",
      preAllocatedVUs: 50,
      maxVUs: 150,
    },
  },
  thresholds: {
    server_errors: ["rate<0.005"],
    "http_req_duration{kind:read}": ["p(95)<300", "p(99)<800"],
    "http_req_duration{kind:write}": ["p(95)<500", "p(99)<1200"],
  },
};

function pick() {
  return users[Math.floor(Math.random() * users.length)];
}

function params(user, kind) {
  return {
    headers: { Authorization: `Bearer ${user.token}`, "Content-Type": "application/json" },
    tags: { kind },
  };
}

function record(res, okStatuses) {
  serverErrors.add(res.status >= 500 || res.status === 0);
  check(res, { "expected status": (r) => okStatuses.includes(r.status) });
}

export function browse() {
  const me = pick();
  record(http.get(`${BASE}/events/${EVENT}/matches`, params(me, "read")), [200, 429]);
  sleep(1 + Math.random() * 2);
  record(http.get(`${BASE}/events/${EVENT}/waves/inbox`, params(me, "read")), [200, 429]);
  record(http.get(`${BASE}/notifications/unread-count`, params(me, "read")), [200, 429]);
  sleep(1 + Math.random() * 3);
  record(http.get(`${BASE}/conversations`, params(me, "read")), [200, 429]);
  sleep(2 + Math.random() * 4);
}

export function connect() {
  const me = pick();
  let other = pick();
  if (other.id === me.id) other = users[(users.indexOf(other) + 1) % users.length];
  const res = http.post(
    `${BASE}/events/${EVENT}/waves`,
    JSON.stringify({ to_user: other.id, source: "directory" }),
    params(me, "write"),
  );
  // 201 new wave, 409 already waved, 429 per-user wave cap: all healthy answers
  record(res, [200, 201, 409, 429]);
  if (res.status !== 201) return;

  const inbox = http.get(`${BASE}/events/${EVENT}/waves/inbox`, params(other, "read"));
  record(inbox, [200, 429]);
  const items = inbox.status === 200 ? inbox.json("items") : [];
  if (!items || items.length === 0) return;
  const accept = http.post(
    `${BASE}/waves/${items[0].id}/respond`,
    JSON.stringify({ action: "accept" }),
    params(other, "write"),
  );
  record(accept, [200, 204, 404, 409]);
  const cid = accept.status === 200 ? accept.json("conversation_id") : null;
  if (!cid) return;
  record(
    http.post(
      `${BASE}/conversations/${cid}/messages`,
      JSON.stringify({ body: "Good to meet you. Coffee stand in ten?" }),
      params(other, "write"),
    ),
    [201, 429],
  );
}
