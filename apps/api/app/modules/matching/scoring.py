"""Pure scoring functions for 05 stages 3 and 4. No I/O, so they are unit-tested directly.

Nothing here may read price, premium, sponsorship or any other money signal:
"money never ranks" (00 §4) is enforced by an import-linter contract and a test.
"""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any

import numpy as np

from app.modules.profiles.public import ProfileData

COMPLEMENTS = {
    ("hire", "get_hired"),
    ("get_hired", "hire"),
    ("raise", "invest"),
    ("invest", "raise"),
    ("sell", "buy"),
    ("buy", "sell"),
}
SAME_INTENT_BONUS = {"learn", "meet", "partner", "cofounder"}
INTENT_LABEL = {
    "hire": "hiring",
    "get_hired": "job seeking",
    "raise": "raising",
    "invest": "investing",
    "sell": "selling",
    "buy": "buying",
    "learn": "learning",
    "cofounder": "co-founder search",
    "partner": "partnerships",
    "meet": "meeting people",
}


@dataclass(frozen=True)
class Config:
    # stage 2
    per_goal_limit: int = 40
    k: int = 60
    # stage 3
    w_semantic: float = 0.60
    w_filters: float = 0.25
    bonus_complement: float = 0.25
    bonus_same: float = 0.10
    priority_w1: float = 1.0
    priority_w2: float = 0.85
    priority_w3: float = 0.70
    neutral_filters: float = 0.5
    # stage 4
    w_goal: float = 0.70
    w_context: float = 0.20
    w_warmth: float = 0.10
    ctx_session: float = 0.40
    ctx_present: float = 0.30
    ctx_city: float = 0.30
    # stage 5
    min_score: float = 0.25
    feed_size: int = 8
    wildcards: int = 2
    wildcard_from: int = 15
    wildcard_to: int = 40
    wildcard_min: float = 0.15
    high_bucket: float = 0.5
    # fairness
    damping_share: float = 0.15
    damping_step: float = 0.03
    damping_cap: float = 0.30
    damping_min_feeds: int = 20
    warmup_min: int = 5
    fanout: int = 15

    def with_overrides(self, values: dict[str, Any]) -> "Config":
        known = {f.name: f.type for f in fields(self)}
        clean: dict[str, Any] = {}
        for name, value in values.items():
            if name in known and isinstance(value, int | float) and not isinstance(value, bool):
                clean[name] = int(value) if known[name] in (int, "int") else float(value)
        return Config(**{**asdict(self), **clean})


@dataclass(frozen=True)
class Fit:
    value: float = 0.0
    semantic: float = 0.0
    filters: float = 0.0
    bonus: float = 0.0
    a_goal: str | None = None
    b_source: str | None = None
    a_intent: str | None = None
    b_intent: str | None = None
    filter_hits: list[str] = field(default_factory=list)


def cosine(u: Any, v: Any) -> float:
    a, b = np.asarray(u, dtype=np.float32), np.asarray(v, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return max(0.0, min(1.0, float(a @ b) / denom))


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _has(needle: str, *haystack: str | None) -> bool:
    n = needle.strip().lower()
    return bool(n) and any(n in (h or "").lower() for h in haystack)


def target_fraction(target: dict[str, Any], b: ProfileData, cfg: Config) -> tuple[float, list[str]]:
    """Fraction of A's specified target fields that B satisfies (05 §4)."""
    goal_text = " ".join(g.raw_input or "" for g in b.goals)
    checks = {
        "role": (target.get("roles") or [], (b.role_title, b.headline)),
        "industry": (
            target.get("industries") or [],
            (b.industry, b.headline, b.offer_text, b.company),
        ),
        "stage": (target.get("stage") or [], (b.bio, b.headline, b.offer_text, goal_text)),
    }
    specified, satisfied, hits = 0, 0, []
    for name, (wanted, haystack) in checks.items():
        if not wanted:
            continue
        specified += 1
        found = [str(w).lower() for w in wanted if _has(str(w), *haystack)]
        if found:
            satisfied += 1
            hits += [f"{name}:{w}" for w in found]
    if specified == 0:
        return cfg.neutral_filters, []
    return satisfied / specified, hits


def fit(a: ProfileData, b: ProfileData, cfg: Config) -> Fit:
    """How well B answers what A is looking for (ordered pair A->B)."""
    weights = {1: cfg.priority_w1, 2: cfg.priority_w2, 3: cfg.priority_w3}
    asks: list[tuple[str | None, str | None, dict[str, Any], Any, float]] = [
        (g.id, g.intent, g.target, g.ask_embedding, weights.get(g.priority, cfg.priority_w3))
        for g in a.goals
        if g.ask_embedding is not None
    ]
    if not asks and a.profile_embedding is not None:  # cold start: no goals yet (05 §9)
        asks = [(None, None, {}, a.profile_embedding, 1.0)]
    offers: list[tuple[str, Any]] = [
        (g.id, g.offer_embedding) for g in b.goals if g.offer_embedding is not None
    ]
    if b.profile_embedding is not None:
        offers.append(("profile", b.profile_embedding))
    best: tuple[float, int, str] | None = None
    for i, (_, _, _, ask_vec, weight) in enumerate(asks):
        for source, offer_vec in offers:
            s = weight * cosine(ask_vec, offer_vec)
            if best is None or s > best[0]:
                best = (s, i, source)
    if best is None:
        return Fit()
    semantic, i, source = best
    goal_id, intent, target, _, _ = asks[i]
    filters, hits = target_fraction(target, b, cfg)
    bonus, b_intent = 0.0, None
    if intent:
        for g in b.goals:
            if (intent, g.intent) in COMPLEMENTS:
                bonus, b_intent = cfg.bonus_complement, g.intent
                break
        else:
            if intent in SAME_INTENT_BONUS and any(g.intent == intent for g in b.goals):
                bonus, b_intent = cfg.bonus_same, intent
    value = clamp01(cfg.w_semantic * semantic + cfg.w_filters * filters + bonus)
    return Fit(value, semantic, filters, bonus, goal_id, source, intent, b_intent, hits)


def pair_scores(
    fit_ab: Fit,
    fit_ba: Fit,
    *,
    both_present: bool,
    warmth_a: float,
    warmth_b: float,
    cfg: Config,
) -> tuple[float, float, dict[str, Any]]:
    """Returns (score in A's feed, score in B's feed, persisted components) per 05 §5-6."""
    goal = math.sqrt(fit_ab.value * fit_ba.value)  # geometric mean: one-sided is near dead
    # shared_session and same_home_city are not collected yet (zones v1.5, city graph v2)
    context = cfg.ctx_present * (1.0 if both_present else 0.0)
    base = cfg.w_goal * goal + cfg.w_context * context
    score_a = base + cfg.w_warmth * warmth_b
    score_b = base + cfg.w_warmth * warmth_a
    matched = [
        {
            "dir": d,
            "a_goal": f.a_goal,
            "b_source": f.b_source,
            "sim": round(f.semantic, 3),
            "a_intent": f.a_intent,
            "b_intent": f.b_intent,
            "filter_hits": f.filter_hits,
        }
        for d, f in (("ab", fit_ab), ("ba", fit_ba))
    ]
    sig_src = [
        [m["a_goal"], m["b_source"], m["a_intent"], m["b_intent"], m["filter_hits"]]
        for m in matched
    ]
    components = {
        "fit_ab": round(fit_ab.value, 3),
        "fit_ba": round(fit_ba.value, 3),
        "goal_score": round(goal, 3),
        "matched": matched,
        "intent_bonus_ab": fit_ab.bonus,
        "intent_bonus_ba": fit_ba.bonus,
        "context": {"shared_session": None, "both_present": both_present, "same_city": False},
        "warmth_a": round(warmth_a, 3),
        "warmth_b": round(warmth_b, 3),
        "score_a": round(score_a, 3),
        "score_b": round(score_b, 3),
        "sig": hashlib.sha256(json.dumps(sig_src).encode()).hexdigest()[:16],
    }
    return score_a, score_b, components


def warmth(accepts: int, received: int) -> float:
    return (accepts + 1) / (received + 2)


def chips_for(components: dict[str, Any], viewer_is_a: bool) -> list[str]:
    """Short labels for the viewer: what they wanted that the other person matches."""
    chips: list[str] = []
    order = ("ab", "ba") if viewer_is_a else ("ba", "ab")
    by_dir = {m["dir"]: m for m in components.get("matched", [])}
    for d in order:
        m = by_dir.get(d)
        if not m:
            continue
        for hit in m.get("filter_hits", []):
            label = hit.split(":", 1)[-1]
            if label not in chips:
                chips.append(label)
        if d == order[0] and m.get("b_intent") and INTENT_LABEL.get(m["b_intent"]):
            label = INTENT_LABEL[m["b_intent"]]
            if label not in chips:
                chips.append(label)
    return chips[:4]


def select_feed(
    ranked: list[tuple[str, float]],
    embeddings: dict[str, Any],
    cfg: Config,
) -> list[tuple[str, bool]]:
    """05 §7: top matches above the floor, then up to two diverse wildcards from the
    middle of the ranking. `ranked` is (peer_id, score) best first."""
    top = [p for p, s in ranked[: cfg.feed_size] if s >= cfg.min_score]
    chosen: list[tuple[str, bool]] = [(p, False) for p in top]
    pool = [
        p
        for p, s in ranked[cfg.wildcard_from - 1 : cfg.wildcard_to]
        if s >= cfg.wildcard_min and embeddings.get(p) is not None
    ]
    picked: list[str] = []
    for _ in range(cfg.wildcards):
        anchors = [embeddings[p] for p in [*top, *picked] if embeddings.get(p) is not None]
        best, best_d = None, -1.0
        for p in pool:
            if p in picked:
                continue
            d = min((1.0 - cosine(embeddings[p], a) for a in anchors), default=1.0)
            if d > best_d:
                best, best_d = p, d
        if best is None:
            break
        picked.append(best)
    return chosen + [(p, True) for p in picked]
