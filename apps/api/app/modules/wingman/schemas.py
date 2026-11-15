from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Action = Literal["draft", "rewrite", "suggest_replies"]
# "Flirt" is not a tone. Professional app (01 §8.4).
Tone = Literal["professional", "casual", "warm", "brief"]


class AssistIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    conversation_id: str = Field(max_length=40)
    action: Action
    text: str | None = Field(default=None, max_length=2000)
    tone: Tone | None = None

    @model_validator(mode="after")
    def _rewrite_needs_text(self) -> "AssistIn":
        if self.action == "rewrite" and not self.text:
            raise ValueError("rewrite needs text")
        return self


class AssistOut(BaseModel):
    options: list[str]
