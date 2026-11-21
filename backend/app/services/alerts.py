from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.db.models import Alert, NotificationAttempt, RiskAssessment
from app.notifications.adapter import MockNotifier, Notifier
from app.repositories.common import flush


def apply_alert_policy(
    db: Session, assessment: RiskAssessment, notifier: Notifier | None = None
) -> Alert | None:
    trigger = assessment.status
    unresolved = list(
        db.scalars(
            select(Alert).where(Alert.batch_id == assessment.batch_id, Alert.resolved_at.is_(None))
        )
    )
    for alert in unresolved:
        if alert.trigger_key == trigger:
            return alert
        alert.resolved_at = utcnow()
    if trigger not in {"early_decay", "spoiling", "insufficient_data"}:
        flush(db)
        return None
    severity = "high" if trigger == "spoiling" else "warning"
    alert = Alert(
        batch_id=assessment.batch_id,
        assessment_id=assessment.id,
        severity=severity,
        trigger_key=trigger,
        message=f"Operational status: {trigger}. Human inspection required. "
        "This is not a food-safety determination.",
    )
    db.add(alert)
    flush(db)
    result = (notifier or MockNotifier()).deliver(alert_id=alert.id, message=alert.message)
    alert.delivery_status = result.status
    db.add(
        NotificationAttempt(
            alert_id=alert.id,
            provider=result.provider,
            status=result.status,
            provider_reference=result.provider_reference,
        )
    )
    flush(db)
    return alert
