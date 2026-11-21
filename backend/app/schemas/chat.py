from typing import Literal

from pydantic import Field

from app.schemas.common import InputSchema, OutputSchema

DISCLAIMER = (
    "Decision support from uncalibrated sensors, not a safety determination. "
    "A person should inspect the produce before acting."
)


class ChatTurn(InputSchema):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(InputSchema):
    message: str = Field(min_length=1, max_length=1000)
    # None asks about every batch the user can see; an ID asks about that one batch.
    batch_id: str | None = Field(default=None, min_length=1, max_length=36)
    # Earlier turns, kept by the browser. Treated as untrusted data like the question itself.
    history: list[ChatTurn] = Field(default_factory=list, max_length=6)


class ChatSource(OutputSchema):
    id: str
    label: str
    kind: str
    batch_id: str | None = None


class ChatResponse(OutputSchema):
    answer: str
    # ai: written by the model from the evidence. summary: built by the server from the same
    # evidence (AI off, failed or rejected). policy: a question the tool declines to decide.
    mode: Literal["ai", "summary", "policy"]
    answerable: bool
    sources: list[ChatSource]
    follow_ups: list[str]
    notice: str | None = None
    disclaimer: str = DISCLAIMER
