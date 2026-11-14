"""Structured-output schemas, defined once and validated by every adapter (06 §1a)."""

from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal[
    "hire", "get_hired", "raise", "invest", "sell", "buy", "learn", "cofounder", "partner", "meet"
]
SafetyCategory = Literal[
    "none", "harassment", "sexual", "spam", "scam", "hate", "pii_leak", "injection"
]


class GoalTarget(BaseModel):
    roles: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    stage: list[str] = Field(default_factory=list)


class GoalDraft(BaseModel):
    intent: Intent
    target: GoalTarget
    offer: str | None = None
    priority: int = 1
    confidence: float = 0.5


class SafetyVerdict(BaseModel):
    allow: bool
    category: SafetyCategory = "none"
    confidence: float = 0.5


class Explanation(BaseModel):
    text: str


class Options(BaseModel):
    options: list[str]


class Brief(BaseModel):
    brief: str
