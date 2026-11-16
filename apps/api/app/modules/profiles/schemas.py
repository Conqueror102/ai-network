from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal[
    "hire", "get_hired", "raise", "invest", "sell", "buy", "learn", "cofounder", "partner", "meet"
]
Visibility = Literal["hidden", "directory", "radar"]


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EventProfileIn(In):
    display_name: str = Field(min_length=1, max_length=40)
    headline: str | None = Field(default=None, max_length=80)
    offer_text: str | None = Field(default=None, max_length=300)
    visibility: Visibility = "directory"
    # off: only people I am matched with can find me or wave at me
    open_to_all: bool = True


class EventCardOut(BaseModel):
    """What other attendees may see. No contact details, no location, no scores."""

    user_id: str
    display_name: str
    photo_url: str | None
    headline: str | None
    offer_text: str | None


class MyEventProfileOut(EventCardOut):
    visibility: str
    open_to_all: bool


class DirectoryCardOut(EventCardOut):
    """A directory row. The extra fields come from the public part of the profile
    and let people scan a list without opening each card."""

    role_title: str | None
    company: str | None
    industry: str | None
    looking_for: list[str]  # the person's active goal intents, e.g. ["hire", "meet"]


class SearchOut(BaseModel):
    items: list[DirectoryCardOut]
    # "smart": ranked by meaning. "keyword": plain text match, used when AI is unavailable.
    mode: Literal["smart", "keyword"]


class Target(In):
    roles: list[str] = Field(default_factory=list, max_length=10)
    industries: list[str] = Field(default_factory=list, max_length=10)
    stage: list[str] = Field(default_factory=list, max_length=10)


class GoalParseIn(In):
    text: str = Field(min_length=3, max_length=500)


class GoalDraftOut(BaseModel):
    intent: str
    target: Target
    offer: str | None
    priority: int
    confidence: float
    raw_input: str


class GoalParseOut(BaseModel):
    goal: GoalDraftOut | None
    manual: bool = False  # true when AI is unavailable: client opens the blank form


class GoalIn(In):
    intent: Intent
    target: Target = Field(default_factory=Target)
    offer: str | None = Field(default=None, max_length=300)
    raw_input: str | None = Field(default=None, max_length=500)
    priority: int = Field(ge=1, le=3)


class GoalPatchIn(In):
    intent: Intent | None = None
    target: Target | None = None
    offer: str | None = Field(default=None, max_length=300)
    priority: int | None = Field(default=None, ge=1, le=3)


class GoalOut(BaseModel):
    id: str
    intent: str
    target: Target
    offer: str | None
    raw_input: str | None
    priority: int
    status: str


class RoomOut(BaseModel):
    event_id: str
    event_name: str
    status: str
    checked_in_count: int
    meeting_points: list[str]
    my_profile: MyEventProfileOut | None
    goals: list[GoalOut]
