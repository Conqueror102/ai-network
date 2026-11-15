from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class SponsorIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    tagline: str | None = Field(default=None, max_length=140)
    url: HttpUrl | None = None


class SponsorOut(BaseModel):
    id: str
    event_id: str
    name: str
    tagline: str | None
    url: str | None
    status: str
