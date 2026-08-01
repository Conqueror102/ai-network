# 05 — Matching Engine Specification

Deterministic pipeline; every constant listed here lives in a `matching_config` settings row so it's tunable without deploys. Initial values below.

## 1. Inputs

Per user per event:
- **Goals** (1–3): `intent`, `target {roles[], industries[], stage[]}`, `offer`, `priority`, `ask_embedding`, `offer_embedding`.
- **Event profile**: `offer_text`, `headline`, `profile_embedding` (= embed of `offer_text + headline + bio`).
- **Context**: session check-ins, radar-active recency, home city [v2], historical responsiveness.

### Embedding contract
- Model `voyage-3.5`, 1024 dims, `input_type="query"` for asks, `"document"` for offers/profiles.
- Ask text template: `"{intent_verb_phrase}. Looking for: roles={roles}; industries={industries}; stage={stage}. {raw_input}"`.
- Offer text template: `"{offer}. Profile: {headline}. {offer_text}"`.
- Re-embed on any goal/profile edit (worker, debounced 30 s).

## 2. Stage 1 — hard filters (SQL)

Candidate set for user A at event E: checked-in ∧ `visibility != 'hidden'` ∧ not blocked (both directions) ∧ no existing wave A↔B ∧ not connected ∧ not skipped-by-A ∧ not self.

## 3. Stage 2 — candidate generation (pgvector)

For each active goal g of A:
```sql
SELECT ep.user_id, 1 - (g.ask_embedding <=> x.emb) AS sim
FROM (goal offer_embeddings ∪ profile_embeddings of candidate set) x
ORDER BY g.ask_embedding <=> x.emb
LIMIT 40;
```
Union candidates across A's goals, dedupe, cap at **K = 60** by best sim. (ivfflat probes = 10.)

## 4. Stage 3 — pairwise fit

For ordered pair (A→B):

```
semantic(A→B)  = max over (a in A.goals, o in B.offers ∪ {B.profile}) cosine_sim(a.ask, o)
filters(A→B)   = matched_target_fraction(a*, B)          # a* = argmax goal above
                 -- fraction of A's specified target fields (role/industry/stage)
                 -- that B's profile satisfies; unspecified fields don't count.
                 -- If A specified ≥1 field: value in [0,1]. If none: 0.5 (neutral).
intent_bonus(A→B) = 0.25 if (a*.intent, any B.goal.intent) ∈ COMPLEMENTS
                    0.10 if equal intents in {learn, meet, partner, cofounder}
                    else 0
COMPLEMENTS = {(hire,get_hired),(get_hired,hire),(raise,invest),(invest,raise),
               (sell,buy),(buy,sell)}

fit(A→B) = clamp01( 0.60*semantic + 0.25*filters + intent_bonus )
```

Priority weighting: multiply each goal's contribution candidate-side by `1.0 / 0.85 / 0.7` for priority 1/2/3 before the max.

## 5. Stage 4 — pair score

```
goal_score  = sqrt( fit(A→B) * fit(B→A) )          # geometric mean: one-sided ≈ dead
context     = 0.40*shared_session + 0.30*both_present_now + 0.30*same_home_city   # each 0|1
warmth      = accept_rate_of_B (smoothed: (accepts+1)/(received+2)), private
serendipity = handled at selection, not in score

score = 0.70*goal_score + 0.20*context + 0.10*warmth
```

`both_present_now` = both users' door check-in within event hours today AND (radar-active within 30 min OR any API activity within 30 min).

## 6. Persisted components (per pair, JSONB)

```json
{
  "fit_ab": 0.74, "fit_ba": 0.68, "goal_score": 0.71,
  "matched": [{"a_goal": "gol_x", "b_source": "gol_y|profile", "sim": 0.81,
               "a_intent": "sell", "b_intent": "buy",
               "filter_hits": ["industry:fintech", "role:cto"]}],
  "intent_bonus_ab": 0.25, "intent_bonus_ba": 0.25,
  "context": {"shared_session": "zon_123|null", "both_present": true, "same_city": false},
  "warmth_b": 0.62, "score": 0.69
}
```
This object is (a) the input to explanation generation, (b) frozen into `match_feedback` on every signal — the training data.

## 7. Stage 5 — selection & explanation

1. Rank B's for A by `score`; drop score < **0.25**.
2. Take top 8. Wildcards: from ranks 15–40, pick up to 2 maximizing profile-embedding *distance* from A's already-selected matches (diversity), require score ≥ 0.15. Label `wildcard=true`.
3. Explanations ("why you two"): Claude call per NEW pair (see 06 §4.2), grounded strictly in `components.matched` + context. Cached in `match_scores.explanation`; regenerate only if components changed materially (goal edited).
4. Feed API returns cards; raw scores never leave the server (`score_bucket`: high ≥ 0.5, else medium).

## 8. Jobs & triggers

| Job | Trigger | Work |
|---|---|---|
| `compute_for_user` | check-in; goal/profile edit (debounced 30 s) | Stages 1–5 for that user vs all checked-in |
| `recompute_event` | every 30 min while event live | Recompute pairs where either side changed since `computed_at`; refresh `both_present_now` |
| `nightly_weights` | post-pilot, weekly | Fit logistic regression: features = component vector, label = positive (`wave_accepted`, `meet_confirmed`) vs negative (`feed_skip`, `wave_not_now`, `chat_died`); propose new weights; human approves before activation |

`chat_died` label: conversation with ≥ 2 messages and no message for 48 h and no meet — logged by nightly job.

## 9. Cold start & fairness

- User with no goals: matchable via `profile_embedding` only; app nags to add goals ("your matches get 3× better").
- Brand-new event (few check-ins): feed shows "warming up" below 5 candidates; recompute on every 10th check-in early on.
- Popularity damping: a user appearing in > 15% of feeds at an event gets a per-appearance penalty `-0.03 × excess_appearances` — spreads attention, protects popular people (works with the inbox cap, 01 §7.4).

## 10. Worked example

A = Victor: goal `sell`, target `{industries:[events], roles:[organizer]}`, offer "AI networking platform", priority 1.
B = Sara: goal `buy` ("tools to improve my conference"), offer "I organize DevCon (3k attendees)".

- semantic(A→B): Victor's ask ("sell to event organizers…") vs Sara's offer/profile → cos ≈ 0.78.
- filters(A→B): industry `events` hit, role `organizer` hit → 1.0.
- intent: (sell, buy) ∈ COMPLEMENTS → +0.25. → `fit(A→B) = 0.60*0.78 + 0.25*1.0 + 0.25 = 0.968 → clamp 0.97`.
- Reverse: Sara's ask vs Victor's offer → semantic 0.74, filters 0.5 (she specified none), bonus 0.25 → `fit(B→A) = 0.82`.
- `goal_score = sqrt(0.97*0.82) = 0.89`. Context: shared session yes, both present yes, same city no → 0.70. Warmth 0.6.
- **score = 0.7*0.89 + 0.2*0.70 + 0.1*0.6 = 0.83** → top of both feeds.
- Contrast: junior dev → famous VC: fit 0.9 / 0.1 → goal_score 0.3 → score ≈ 0.36 → mid-list at best.
