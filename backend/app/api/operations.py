from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import administrator, current_user, operator
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.time import utcnow
from app.db.models import Alert, Batch, DecisionLog, NotificationAttempt, RiskAssessment, User
from app.db.session import get_db, get_settings
from app.repositories.assessments import latest_assessment
from app.repositories.common import accessible_batches, flush, paginate, require_batch
from app.schemas.common import Page, Pagination
from app.schemas.operations import (
    AlertOut,
    AssessmentOut,
    AttemptOut,
    DecisionCreate,
    DecisionOut,
    PriorityOut,
)
from app.services.assessments import assess
from app.services.priorities import rank
from app.services.resources import audit

router = APIRouter(prefix="/api/v1", tags=["operations"], dependencies=[Depends(current_user)])


@router.post("/batches/{batch_id}/assessments", response_model=AssessmentOut, status_code=201)
def request_assessment(
    batch_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(operator),
    settings: Settings = Depends(get_settings),
) -> RiskAssessment:
    return assess(db, batch_id, actor, settings)


@router.get("/batches/{batch_id}/assessment", response_model=AssessmentOut)
def latest(
    batch_id: str, db: Session = Depends(get_db), actor: User = Depends(current_user)
) -> RiskAssessment:
    require_batch(db, batch_id, actor)
    assessment = latest_assessment(db, batch_id)
    if assessment is None:
        raise DomainError(404, "not_found", "No assessment has been recorded")
    return assessment


@router.get("/batches/{batch_id}/assessments", response_model=Page[AssessmentOut])
def history(
    batch_id: str,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> Page:
    require_batch(db, batch_id, actor)
    return paginate(
        db,
        select(RiskAssessment)
        .where(RiskAssessment.batch_id == batch_id)
        .order_by(RiskAssessment.created_at.desc(), RiskAssessment.id.desc()),
        page,
    )


@router.get("/priorities", response_model=PriorityOut)
def priorities(
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> PriorityOut:
    return rank(db, actor, settings, page)


@router.get("/alerts", response_model=Page[AlertOut])
def alerts(
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
    batch_id: str | None = None,
    acknowledged: bool | None = None,
    resolved: bool | None = None,
) -> Page:
    query = select(Alert).where(
        Alert.batch_id.in_(accessible_batches(actor).with_only_columns(Batch.id))
    )
    if batch_id:
        require_batch(db, batch_id, actor)
        query = query.where(Alert.batch_id == batch_id)
    if acknowledged is not None:
        query = query.where(
            Alert.acknowledged_at.is_not(None) if acknowledged else Alert.acknowledged_at.is_(None)
        )
    if resolved is not None:
        query = query.where(
            Alert.resolved_at.is_not(None) if resolved else Alert.resolved_at.is_(None)
        )
    return paginate(db, query.order_by(Alert.created_at.desc(), Alert.id), page)


def require_alert(db: Session, alert_id: str, actor: User) -> Alert:
    alert = db.scalar(select(Alert).where(Alert.id == alert_id).with_for_update())
    if alert is None:
        raise DomainError(404, "not_found", "Alert not found")
    require_batch(db, alert.batch_id, actor)
    return alert


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge(
    alert_id: str, db: Session = Depends(get_db), actor: User = Depends(operator)
) -> Alert:
    alert = require_alert(db, alert_id, actor)
    if alert.acknowledged_at is None:
        alert.acknowledged_at, alert.acknowledged_by = utcnow(), actor.id
        audit(
            db,
            actor,
            "alert_acknowledged",
            alert.batch_id,
            {"alert_id": alert.id},
            "Operator acknowledged the alert; acknowledgement is not resolution",
        )
        flush(db)
    return alert


@router.get("/alerts/{alert_id}/attempts", response_model=Page[AttemptOut])
def attempts(
    alert_id: str,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> Page:
    require_alert(db, alert_id, actor)
    return paginate(
        db,
        select(NotificationAttempt)
        .where(NotificationAttempt.alert_id == alert_id)
        .order_by(NotificationAttempt.created_at, NotificationAttempt.id),
        page,
    )


@router.post("/batches/{batch_id}/decisions", response_model=DecisionOut, status_code=201)
def record_decision(
    batch_id: str,
    payload: DecisionCreate,
    db: Session = Depends(get_db),
    actor: User = Depends(operator),
) -> DecisionLog:
    require_batch(db, batch_id, actor)
    if payload.decision_type != "priority_override" and payload.override_rank is not None:
        raise DomainError(422, "invalid_override", "Only priority overrides accept override_rank")
    decision = DecisionLog(
        batch_id=batch_id,
        actor_id=actor.id,
        decision_type=payload.decision_type,
        rationale=payload.rationale,
        input_references={"override_rank": payload.override_rank},
        policy_version="inspection-priority-v1",
    )
    db.add(decision)
    flush(db)
    return decision


@router.get("/batches/{batch_id}/decisions", response_model=Page[DecisionOut])
def decisions(
    batch_id: str,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
) -> Page:
    require_batch(db, batch_id, actor)
    return paginate(
        db,
        select(DecisionLog)
        .where(DecisionLog.batch_id == batch_id)
        .order_by(DecisionLog.created_at.desc(), DecisionLog.id),
        page,
    )


@router.get("/audit", response_model=Page[DecisionOut], dependencies=[Depends(administrator)])
def audit_log(page: Pagination = Depends(), db: Session = Depends(get_db)) -> Page:
    return paginate(
        db, select(DecisionLog).order_by(DecisionLog.created_at.desc(), DecisionLog.id), page
    )
