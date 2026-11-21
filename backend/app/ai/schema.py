import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# One definition of what an AI answer may never claim, shared by explanations and chat.
UNSUPPORTED_CLAIMS = [
    r"\b(?:batch|produce|tomatoes|food|it)\s+(?:is|are)\s+(?:spoiled|rotten|safe|unsafe)\b",
    r"\b(?:safe|unsafe|fit)\s+(?:to\s+(?:eat|sell|consume)|for\s+(?:sale|consumption))\b",
    r"\b(?:shelf[ -]?life|days?\s+(?:left|remaining))\b",
    r"\b(?:sell|dispose|discard)\s+(?:this|the|these|all)\b",
    r"\b(?:certified|guaranteed|definitely\s+spoiled)\b",
]


def contains_unsupported_claim(*texts: str) -> bool:
    content = " ".join(texts).lower()
    return any(re.search(pattern, content) for pattern in UNSUPPORTED_CLAIMS)


class Explanation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["fresh", "early_decay", "spoiling", "insufficient_data"]
    risk_interpretation: str = Field(min_length=1, max_length=3000)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    suggested_next_step: str = Field(min_length=1, max_length=1500)
    uncertainty: str = Field(min_length=1, max_length=1500)
    human_review_required: Literal[True]

    @model_validator(mode="after")
    def reject_safety_claims(self) -> "Explanation":
        if contains_unsupported_claim(
            self.risk_interpretation, self.suggested_next_step, self.uncertainty
        ):
            raise ValueError("Output contains unsupported safety or consequential claims")
        return self


class ChatAnswer(BaseModel):
    """A chat reply. The model may only answer from evidence the server supplied."""

    model_config = ConfigDict(extra="forbid", strict=True)
    answer: str = Field(min_length=1, max_length=2500)
    evidence_ids: list[str] = Field(max_length=20)
    follow_ups: list[str] = Field(max_length=3)
    answerable: bool

    @model_validator(mode="after")
    def grounded_and_safe(self) -> "ChatAnswer":
        if self.answerable and not self.evidence_ids:
            raise ValueError("An answer must cite the evidence it uses")
        if any(len(item) > 120 or not item.strip() for item in self.follow_ups):
            raise ValueError("Follow-up suggestions must be short and non-empty")
        if contains_unsupported_claim(self.answer, *self.follow_ups):
            raise ValueError("Output contains unsupported safety or consequential claims")
        return self


def validate_explanation(raw: str, *, supplied_ids: set[str], status: str) -> Explanation:
    result = Explanation.model_validate_json(raw)
    if result.status != status:
        raise ValueError("AI cannot change deterministic status")
    if not set(result.evidence_ids) <= supplied_ids:
        raise ValueError("AI cited evidence that was not supplied")
    if len(set(result.evidence_ids)) != len(result.evidence_ids):
        raise ValueError("Duplicate evidence citations")
    return result


def validate_chat_answer(raw: str, *, supplied_ids: set[str]) -> ChatAnswer:
    result = ChatAnswer.model_validate_json(raw)
    if not set(result.evidence_ids) <= supplied_ids:
        raise ValueError("AI cited evidence that was not supplied")
    if len(set(result.evidence_ids)) != len(result.evidence_ids):
        raise ValueError("Duplicate evidence citations")
    return result
