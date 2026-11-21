from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.schemas.common import InputSchema, OutputSchema
from app.schemas.resources import RiskStatus


class AssessmentOut(OutputSchema):
    id: str
    batch_id: str
    actor_id: str
    episode_id: str
    status: RiskStatus
    candidate_status: RiskStatus
    score: float | None
    features: dict[str, Any]
    quality_flags: list[str]
    input_references: dict[str, Any]
    explanation: str
    recommendation: str
    uncertainty: str
    human_review_required: bool
    ai_status: Literal["ok", "disabled", "failed", "invalid_output"]
    ai_job_status: str
    provider: str | None
    model: str | None
    rules_version: str
    policy_snapshot: dict[str, Any]
    prompt_version: str
    workflow_version: str
    retrieved_evidence_ids: list[str]
    cited_evidence_ids: list[str]
    ai_explanation: dict[str, Any] | None
    created_at: datetime


class AlertOut(OutputSchema):
    id: str
    batch_id: str
    assessment_id: str
    severity: str
    trigger_key: str
    message: str
    delivery_status: str
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    resolved_at: datetime | None
    created_at: datetime


class DecisionOut(OutputSchema):
    id: str
    batch_id: str | None
    actor_id: str | None
    decision_type: str
    input_references: dict[str, Any]
    rationale: str
    policy_version: str
    created_at: datetime


class DecisionCreate(InputSchema):
    decision_type: Literal["inspection", "annotation", "priority_override"] = "annotation"
    rationale: str = Field(min_length=1, max_length=4000)
    override_rank: int | None = Field(default=None, ge=1, le=100000)


class PriorityItem(InputSchema):
    batch_id: str
    identifier: str
    rank: int
    computed_rank: int = 1
    override_rank: int | None = None
    override_rationale: str | None = None
    override_record_id: str | None = None
    score: float
    status: RiskStatus
    factors: dict[str, float]
    simulated: bool
    assessment_id: str | None
    advisory: str = "Inspect and review before any sale or disposal decision."


class PriorityOut(InputSchema):
    items: list[PriorityItem]
    total: int
    limit: int
    offset: int
    ranking_meaningful: bool
    policy_version: str = "inspection-priority-v1"


class AttemptOut(OutputSchema):
    id: str
    alert_id: str
    provider: str
    status: str
    provider_reference: str | None
    created_at: datetime
