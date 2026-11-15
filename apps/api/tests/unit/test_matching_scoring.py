"""05 §4-§7 as pure functions."""

import math

from app.adapters.embeddings.fake import FakeEmbeddings
from app.modules.matching import scoring
from app.modules.matching.scoring import Config
from app.modules.profiles.public import GoalData, ProfileData

emb = FakeEmbeddings._one
cfg = Config()


def person(uid, *, goals=(), headline=None, offer=None, role=None, industry=None, bio=None):
    gs = [
        GoalData(
            id=f"gol_{uid}{i}",
            intent=intent,
            target=target,
            offer=goal_offer,
            raw_input=ask,
            priority=i + 1,
            ask_embedding=emb(ask),
            offer_embedding=emb(f"{goal_offer or ''} {headline or ''} {offer or ''}"),
        )
        for i, (intent, target, ask, goal_offer) in enumerate(goals)
    ]
    return ProfileData(
        user_id=uid,
        display_name=uid,
        headline=headline,
        offer_text=offer,
        visibility="directory",
        profile_embedding=emb(f"{offer or ''} {headline or ''} {bio or ''}"),
        goals=gs,
        role_title=role,
        company=None,
        industry=industry,
        skills=[],
        bio=bio,
    )


VICTOR = person(
    "victor",
    goals=[
        (
            "sell",
            {"industries": ["events"], "roles": ["organizer"]},
            "sell networking platform to conference organizers events",
            "AI networking platform for conference events",
        )
    ],
    headline="Founder building event tech",
    offer="AI networking platform for conference events",
)
SARA = person(
    "sara",
    goals=[("buy", {}, "buy tools platform to improve my conference events", "I organize DevCon")],
    headline="Conference organizer, events",
    offer="I organize DevCon conference events",
    role="Organizer",
    industry="events",
)
VC = person(
    "vc",
    goals=[("invest", {"stage": ["series b"]}, "invest in series b logistics companies", None)],
    headline="Partner at a logistics fund",
)
JUNIOR = person(
    "junior",
    goals=[("raise", {"roles": ["investor"]}, "raise money from a logistics fund partner", None)],
    headline="Student developer",
)


def test_complementary_pair_scores_high_both_ways():
    ab, ba = scoring.fit(VICTOR, SARA, cfg), scoring.fit(SARA, VICTOR, cfg)
    assert ab.filters == 1.0 and set(ab.filter_hits) == {"role:organizer", "industry:events"}
    assert ab.bonus == 0.25 and ab.b_intent == "buy"
    assert ba.filters == 0.5 and ba.bonus == 0.25  # she specified no target: neutral
    assert ab.value > 0.6 and ba.value > 0.5
    score_a, score_b, comp = scoring.pair_scores(
        ab, ba, both_present=True, warmth_a=0.5, warmth_b=0.6, cfg=cfg
    )
    goal = math.sqrt(ab.value * ba.value)
    assert math.isclose(score_a, 0.7 * goal + 0.2 * 0.3 + 0.1 * 0.6)
    assert math.isclose(score_b, 0.7 * goal + 0.2 * 0.3 + 0.1 * 0.5)
    assert comp["goal_score"] == round(goal, 3) and len(comp["matched"]) == 2
    assert scoring.chips_for(comp, viewer_is_a=True)[:2] == ["organizer", "events"]


def test_one_sided_interest_is_nearly_dead():
    wants, unwanted = scoring.fit(JUNIOR, VC, cfg), scoring.fit(VC, JUNIOR, cfg)
    assert wants.value > 2 * unwanted.value
    one_sided, _, _ = scoring.pair_scores(
        wants, unwanted, both_present=False, warmth_a=0.5, warmth_b=0.5, cfg=cfg
    )
    mutual, _, _ = scoring.pair_scores(
        scoring.fit(VICTOR, SARA, cfg),
        scoring.fit(SARA, VICTOR, cfg),
        both_present=False,
        warmth_a=0.5,
        warmth_b=0.5,
        cfg=cfg,
    )
    assert one_sided < mutual


def test_priority_weights_and_cold_start():
    two = person(
        "two",
        goals=[
            ("learn", {}, "learn about gardening", None),
            ("sell", {}, "sell networking platform to conference organizers events", None),
        ],
    )
    f = scoring.fit(two, SARA, cfg)
    assert f.a_goal == "gol_two1" and f.a_intent == "sell"
    first = scoring.fit(VICTOR, SARA, cfg)
    assert f.semantic < first.semantic  # same ask at priority 2 counts for 0.85
    nobody = person("nobody", headline="Conference events organizer")
    cold = scoring.fit(nobody, SARA, cfg)
    assert cold.a_goal is None and cold.filters == 0.5 and cold.bonus == 0 and cold.value > 0
    empty = ProfileData("x", "x", None, None, "directory", None, [], None, None, None, [], None)
    assert scoring.fit(empty, SARA, cfg).value == 0.0


def test_selection_floor_and_diverse_wildcards():
    ranked = [(f"p{i}", 0.9 - i * 0.02) for i in range(40)]
    vecs = {p: emb("fintech payments") for p, _ in ranked}
    vecs["p20"] = emb("marine biology")
    vecs["p30"] = emb("classical music")
    feed = scoring.select_feed(ranked, vecs, cfg)
    assert [p for p, wild in feed if not wild] == [f"p{i}" for i in range(8)]
    assert {p for p, wild in feed if wild} == {"p20", "p30"}
    low = [(f"p{i}", 0.2) for i in range(10)]
    assert scoring.select_feed(low, {}, cfg) == []  # below the floor: nothing, not filler


def test_config_overrides_ignore_unknown_and_non_numbers():
    c = cfg.with_overrides({"feed_size": 3, "w_goal": 0.5, "nope": 1, "k": "60", "min_score": True})
    assert (c.feed_size, c.w_goal, c.k, c.min_score) == (3, 0.5, 60, 0.25)
    assert scoring.warmth(0, 0) == 0.5 and scoring.warmth(3, 4) == 4 / 6
