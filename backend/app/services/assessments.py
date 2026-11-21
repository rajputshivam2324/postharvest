from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gemini import PROMPT_VERSION
from app.core.config import Settings
from app.core.time import utcnow
from app.db.models import Batch, DecisionLog, EpisodeSummary, ExplanationJob, RiskAssessment, User
from app.repositories.assessments import load_window
from app.repositories.common import flush, require_batch
from app.risk.engine import evaluate, transition
from app.services.alerts import apply_alert_policy


def assess(db: Session, batch_id: str, actor: User, settings: Settings) -> RiskAssessment:
    require_batch(db, batch_id, actor, writable=True)
    # Serialize assessments/alert decisions per batch; worker enrichment cannot change this state.
    batch = db.scalars(select(Batch).where(Batch.id == batch_id).with_for_update()).one()
    now = utcnow()
    policy = settings.risk_policy
    start = now - timedelta(seconds=policy.window_seconds)
    samples, baselines, devices = load_window(db, batch_id, start, now)
    result = evaluate(
        samples,
        baselines,
        now=now,
        commodity=batch.commodity,
        expected_devices=devices,
        policy=policy,
    )
    status, pending, count = transition(
        batch.status,
        result.candidate_status,
        result.score,
        pending=batch.pending_status,
        count=batch.recovery_count,
        last_signature=batch.last_assessment_signature,
        signature=result.signature,
        policy=policy,
    )
    previous = batch.status
    batch.status, batch.pending_status, batch.recovery_count = status, pending, count
    batch.last_assessment_signature = result.signature
    episode = EpisodeSummary(
        batch_id=batch_id,
        window_start=start,
        window_end=now,
        window_seconds=policy.window_seconds,
        statistics=result.features,
        quality_flags=result.quality_flags,
        engine_version=policy.version,
    )
    db.add(episode)
    flush(db)
    queued = bool(settings.gemini_api_key and result.score is not None)
    assessment = RiskAssessment(
        batch_id=batch_id,
        actor_id=actor.id,
        episode_id=episode.id,
        status=status,
        candidate_status=result.candidate_status,
        score=result.score,
        features=result.features,
        quality_flags=result.quality_flags,
        input_references={
            "reading_ids": result.reading_ids,
            "baseline_ids": result.baseline_ids,
            "signature": result.signature,
        },
        explanation=result.explanation,
        recommendation=result.recommendation,
        uncertainty=result.uncertainty,
        ai_status="disabled",
        ai_job_status="pending" if queued else "not_requested",
        rules_version=policy.version,
        policy_snapshot=policy.model_dump(),
        prompt_version=PROMPT_VERSION,
        created_at=now,
    )
    db.add(assessment)
    flush(db)
    if queued:
        db.add(ExplanationJob(assessment_id=assessment.id))
    db.add(
        DecisionLog(
            batch_id=batch_id,
            actor_id=actor.id,
            decision_type="assessment",
            input_references={"assessment_id": assessment.id, **assessment.input_references},
            rationale=f"{previous} -> {status}; candidate={result.candidate_status}; "
            f"recovery_count={count}",
            policy_version=policy.version,
        )
    )
    if previous != status:
        db.add(
            DecisionLog(
                batch_id=batch_id,
                actor_id=actor.id,
                decision_type="state_transition",
                input_references={"assessment_id": assessment.id},
                rationale=f"{previous} -> {status}",
                policy_version=policy.version,
            )
        )
    apply_alert_policy(db, assessment)
    # Deterministic summaries are stored as retrievable evidence even with AI disabled.
    from app.retrieval.indexing import index_assessment_inputs

    index_assessment_inputs(db, batch, assessment, episode)
    flush(db)
    return assessment
