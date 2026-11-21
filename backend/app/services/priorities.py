from datetime import datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import as_utc, utcnow
from app.db.models import Batch, DecisionLog, RiskAssessment, User
from app.repositories.common import accessible_batches
from app.schemas.common import Pagination
from app.schemas.operations import PriorityItem, PriorityOut
from app.schemas.resources import RiskStatus


def rank(
    db: Session, actor: User, settings: Settings, page: Pagination, *, now: datetime | None = None
) -> PriorityOut:
    now = now or utcnow()
    batches = list(db.scalars(accessible_batches(actor).where(Batch.archived.is_(False))))
    ids = [b.id for b in batches]
    ranked_assessments = (
        select(
            RiskAssessment.id,
            func.row_number()
            .over(
                partition_by=RiskAssessment.batch_id,
                order_by=[RiskAssessment.created_at.desc(), RiskAssessment.id.desc()],
            )
            .label("position"),
        )
        .where(RiskAssessment.batch_id.in_(ids))
        .subquery()
    )
    latest = list(
        db.scalars(
            select(RiskAssessment)
            .join(ranked_assessments, RiskAssessment.id == ranked_assessments.c.id)
            .where(ranked_assessments.c.position == 1)
        )
    )
    by_batch = {a.batch_id: a for a in latest}
    items = []
    for batch in batches:
        assessment = by_batch.get(batch.id)
        timestamp = assessment.features.get("latest_source_timestamp") if assessment else None
        stale = (
            not timestamp
            or (now - as_utc(datetime.fromisoformat(timestamp))).total_seconds()
            > settings.risk_policy.stale_seconds
        )
        inadequate = not assessment or assessment.status == "insufficient_data"
        factors = {
            "deterministic_risk": (assessment.score or 0) * settings.priority_risk_weight
            if assessment
            else 0,
            "stale_data_inspection": settings.priority_stale_bonus if stale else 0,
            "insufficient_evidence_inspection": settings.priority_insufficient_bonus
            if inadequate
            else 0,
        }
        retained_floor = (
            settings.risk_policy.high_threshold
            if batch.status == "spoiling"
            else settings.risk_policy.early_threshold
            if batch.status == "early_decay"
            else 0
        )
        factors["state_hysteresis_retention"] = max(
            0, retained_floor * settings.priority_risk_weight - factors["deterministic_risk"]
        )
        items.append(
            PriorityItem(
                batch_id=batch.id,
                identifier=batch.identifier,
                rank=1,
                score=round(sum(factors.values()), 3),
                status=cast(RiskStatus, batch.status),
                factors=factors,
                assessment_id=assessment.id if assessment else None,
                simulated=bool(assessment and assessment.features.get("simulated")),
            )
        )
    items.sort(key=lambda item: (-item.score, item.identifier, item.batch_id))
    for position, item in enumerate(items, 1):
        item.computed_rank = position
    latest_overrides = (
        select(
            DecisionLog.id,
            func.row_number()
            .over(
                partition_by=DecisionLog.batch_id,
                order_by=[DecisionLog.created_at.desc(), DecisionLog.id.desc()],
            )
            .label("position"),
        )
        .where(DecisionLog.batch_id.in_(ids), DecisionLog.decision_type == "priority_override")
        .subquery()
    )
    overrides = list(
        db.scalars(
            select(DecisionLog)
            .join(latest_overrides, DecisionLog.id == latest_overrides.c.id)
            .where(latest_overrides.c.position == 1)
        )
    )
    by_id = {entry.batch_id: entry for entry in overrides}
    for item in items:
        override = by_id.get(item.batch_id)
        if override and override.input_references.get("override_rank") is not None:
            item.override_rank = override.input_references["override_rank"]
            item.override_rationale = override.rationale
            item.override_record_id = override.id
    items.sort(
        key=lambda item: (
            item.override_rank if item.override_rank is not None else item.computed_rank,
            0 if item.override_rank is not None else 1,
            item.computed_rank,
            item.batch_id,
        )
    )
    for position, item in enumerate(items, 1):
        item.rank = position
    return PriorityOut(
        items=items[page.offset : page.offset + page.limit],
        total=len(items),
        limit=page.limit,
        offset=page.offset,
        ranking_meaningful=len(items) >= 2,
    )
