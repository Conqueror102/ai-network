"""Fake responders so the whole app runs offline with plausible AI output.

Registered on the FakeLLM adapter when LLM_PROVIDER=fake (dev, tests, CI).
"""

import json
import re
from typing import Any

from pydantic import BaseModel

from app.adapters.llm.fake import FakeLLM
from app.adapters.llm.port import Message
from app.modules.ai import schemas

_INTENTS = [
    ("get_hired", r"\b(job|looking for (a )?(role|work)|get hired|open to work)\b"),
    ("hire", r"\b(hire|hiring|recruit)"),
    ("raise", r"\b(raise|raising|fundrais|investors?\b.*(for|in) (my|our))"),
    ("invest", r"\b(invest in|investing|deploy capital|looking to invest)"),
    ("sell", r"\b(sell|customers|clients|leads)\b"),
    ("buy", r"\b(buy|vendor|supplier|procure)"),
    ("cofounder", r"\bco-?founder"),
    ("partner", r"\bpartner"),
    ("learn", r"\b(learn|mentor|advice)"),
]
_ROLES = [
    "engineer",
    "developer",
    "designer",
    "founder",
    "investor",
    "marketer",
    "product",
    "sales",
    "cto",
    "ceo",
    "organizer",
    "recruiter",
    "data scientist",
]
_INDUSTRIES = [
    "fintech",
    "healthtech",
    "edtech",
    "agritech",
    "ai",
    "logistics",
    "events",
    "ecommerce",
    "energy",
    "media",
    "saas",
]
_STAGES = ["pre-seed", "seed", "series a", "series b", "growth"]
_BAD = {
    "harassment": r"\b(idiot|stupid|shut up|loser)\b",
    "sexual": r"\b(sexy|hot stuff|date me|hook ?up)\b",
    "scam": r"\b(send (me )?money|wire transfer|double your|bitcoin giveaway)\b",
    "hate": r"\b(hate (all|those))\b",
    "injection": r"(ignore (all )?(previous|prior) instructions|system prompt)",
    "pii_leak": r"(\+?\d[\d\s-]{8,}\d|[\w.]+@[\w.]+\.\w+)",
    "spam": r"(buy now|limited offer|click here)",
}


def _user_text(messages: list[Message]) -> str:
    content = messages[-1]["content"]
    return content if isinstance(content, str) else json.dumps(content)


def _data(text: str, source: str | None = None) -> str:
    pattern = (
        rf'<user_data source="{source}">(.*?)</user_data>'
        if source
        else r"<user_data[^>]*>(.*?)</user_data>"
    )
    return " ".join(re.findall(pattern, text, flags=re.S))


def goal_parser(messages: list[Message], schema: type[BaseModel] | None) -> Any:
    text = _data(_user_text(messages)).lower()
    intent = next((i for i, pat in _INTENTS if re.search(pat, text)), "meet")
    offer = None
    m = re.search(r"\bi (?:can |could )?(?:offer|bring|build|run|have)\b(.*)", text)
    if m:
        offer = m.group(0).strip().rstrip(".")[:300]
    return schemas.GoalDraft(
        intent=intent,  # type: ignore[arg-type]
        target=schemas.GoalTarget(
            roles=[r for r in _ROLES if re.search(rf"\b{r}s?\b", text)],
            industries=[i for i in _INDUSTRIES if re.search(rf"\b{i}\b", text)],
            stage=[s for s in _STAGES if s in text],
        ),
        offer=offer,
        priority=1,
        confidence=0.6 if intent == "meet" else 0.85,
    )


def safety_screen(messages: list[Message], schema: type[BaseModel] | None) -> Any:
    text = _data(_user_text(messages)).lower()
    for category, pat in _BAD.items():
        if re.search(pat, text):
            return schemas.SafetyVerdict(
                allow=False,
                category=category,  # type: ignore[arg-type]
                confidence=0.95,
            )
    return schemas.SafetyVerdict(allow=True, category="none", confidence=0.9)


def _chips(text: str) -> list[str]:
    m = re.search(r"CHIPS: (.*)", text)
    return [c.strip() for c in m.group(1).split("|") if c.strip()] if m else []


def match_explainer(messages: list[Message], schema: type[BaseModel] | None) -> Any:
    chips = _chips(_user_text(messages))
    return schemas.Explanation(text=f"You match on {', '.join(chips) or 'shared goals'}.")


def icebreakers(messages: list[Message], schema: type[BaseModel] | None) -> Any:
    chips = _chips(_user_text(messages)) or ["this event"]
    return schemas.Options(
        options=[
            f"Hi! I saw we both care about {chips[0]}. What brought you here?",
            "Good to connect. What are you hoping to get out of today?",
        ]
    )


def chat_assist(messages: list[Message], schema: type[BaseModel] | None) -> Any:
    text = _user_text(messages)
    if re.search(r"TONE: (flirt|romantic)", text):
        opts = ["tone_unavailable"]
    elif "ACTION: suggest_replies" in text:
        opts = [
            "Sounds good, tell me more.",
            "Happy to. When works for you?",
            "Interesting. How did you get into that?",
        ]
    elif "ACTION: rewrite" in text:
        opts = ["Rewritten: " + _data(text, "draft")[:200]]
    else:
        opts = ["Great to meet you. Shall we grab ten minutes after this session?"]
    return schemas.Options(options=opts) if schema else opts[0]


def followup_drafts(messages: list[Message], schema: type[BaseModel] | None) -> Any:
    m = re.search(r"EVENT: (.*)", _user_text(messages))
    where = m.group(1).strip() if m else "the event"
    return schemas.Options(
        options=[f"Great meeting you at {where}. Keen to continue our conversation this week?"]
    )


def meeting_brief(messages: list[Message], schema: type[BaseModel] | None) -> Any:
    return schemas.Brief(
        brief="**Who they are**\nSee their card.\n\n**Talking points**\n"
        "- Shared goals\n- Their offer\n- Next step"
    )


def install(fake: FakeLLM) -> None:
    fake.responders.update(
        {
            "goal_parser": goal_parser,
            "safety_screen": safety_screen,
            "match_explainer": match_explainer,
            "icebreakers": icebreakers,
            "chat_assist": chat_assist,
            "followup_drafts": followup_drafts,
            "meeting_brief": meeting_brief,
        }
    )
