import argparse
import logging
import time
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.gemini import PROMPT_VERSION, GeminiAdapter
from app.core.config import Settings
from app.core.time import utcnow
from app.db.models import DecisionLog, EvidenceChunk, ExplanationJob, RiskAssessment, User
from app.db.session import build_engine, session_factory
from app.repositories.common import require_batch
from app.retrieval.query import retrieve, scoped_query
from app.workflow.explanation import build_workflow

logger = logging.getLogger("harvest.worker")
MAX_ATTEMPTS = 3


def claim(
    factory: sessionmaker[Session], settings: Settings, *, assessment_id: str | None = None
) -> tuple[str, str] | None:
    # Lease exceeds all bounded embedding/generation calls. Crashed workers can be reclaimed.
    lease_seconds = (settings.retrieval_top_k + 2) * settings.ai_timeout_seconds + 120
    cutoff = utcnow() - timedelta(seconds=lease_seconds)
    with factory.begin() as db:
        exhausted = list(
            db.scalars(
                select(ExplanationJob)
                .where(
                    ExplanationJob.status == "running",
                    ExplanationJob.locked_at < cutoff,
                    ExplanationJob.attempts >= MAX_ATTEMPTS,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for expired_job in exhausted:
            expired_job.status, expired_job.error_code, expired_job.finished_at = (
                "failed",
                "retry_exhausted",
                utcnow(),
            )
            assessment = db.get(RiskAssessment, expired_job.assessment_id)
            if assessment:
                assessment.ai_status, assessment.ai_job_status = "failed", "failed"
        job_query = (
            select(ExplanationJob)
            .where(
                or_(
                    ExplanationJob.status == "pending",
                    and_(ExplanationJob.status == "running", ExplanationJob.locked_at < cutoff),
                ),
                ExplanationJob.attempts < MAX_ATTEMPTS,
            )
            .order_by(ExplanationJob.created_at, ExplanationJob.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if assessment_id is not None:
            job_query = job_query.where(ExplanationJob.assessment_id == assessment_id)
        job = db.scalar(job_query)
        if job is None:
            return None
        token = str(uuid4())
        job.status, job.lease_token, job.locked_at = "running", token, utcnow()
        job.attempts += 1
        assessment = db.get(RiskAssessment, job.assessment_id)
        if assessment:
            assessment.ai_job_status = "running"
        return job.id, token


def enrich(factory: sessionmaker[Session], settings: Settings, job_id: str) -> dict[str, Any]:
    adapter = GeminiAdapter(settings)
    with factory() as db:
        job = db.get(ExplanationJob, job_id)
        if job is None:
            raise ValueError("Job no longer exists")
        assessment = db.get(RiskAssessment, job.assessment_id)
        if assessment is None:
            raise ValueError("Assessment no longer exists")
        actor = db.get(User, assessment.actor_id)
        if actor is None or not actor.active:
            raise ValueError("Assessment actor is no longer authorized")
        batch = require_batch(db, assessment.batch_id, actor)
        snapshot: dict[str, Any] = {
            "batch_id": batch.id,
            "actor_id": actor.id,
            "assessment_id": assessment.id,
            "at": assessment.created_at,
            "status": assessment.status,
            "features": assessment.features,
            "score": assessment.score,
        }
        # Bound indexing work per job, using precisely the same scope as read-only retrieval.
        unembedded = list(
            db.scalars(
                scoped_query(db, batch.id, actor, assessment.created_at)
                .where(
                    or_(
                        EvidenceChunk.embedding.is_(None),
                        EvidenceChunk.embedding_model != settings.gemini_embedding_model,
                    )
                )
                .order_by(EvidenceChunk.created_at.desc(), EvidenceChunk.id)
                .limit(settings.retrieval_top_k)
            )
        )
        documents = [(e.id, e.content_hash, e.text) for e in unembedded]
    query_embedding = None
    if adapter.enabled and snapshot["score"] is not None:
        try:
            for chunk_id, content_hash, text in documents:
                embedding = adapter.embed(text)
                with factory.begin() as db:
                    chunk = db.get(EvidenceChunk, chunk_id)
                    if chunk and chunk.content_hash == content_hash:
                        chunk.embedding, chunk.embedding_model = (
                            embedding,
                            settings.gemini_embedding_model,
                        )
            query_embedding = adapter.embed(
                "Operational assessment: " + str(snapshot["status"]), task_type="RETRIEVAL_QUERY"
            )
        except Exception:
            # Generation can still use fixed structured retrieval after embedding outages.
            logger.info("embedding_fallback job_id=%s", job_id)
    with factory() as db:
        actor = db.get(User, snapshot["actor_id"])
        if actor is None or not actor.active:
            raise ValueError("Actor authorization changed")
        evidence = retrieve(
            db,
            batch_id=snapshot["batch_id"],
            actor=actor,
            at=snapshot["at"],
            settings=settings,
            query_embedding=query_embedding,
            exclude_assessment_id=snapshot["assessment_id"],
        )
    graph = build_workflow(adapter, lambda: evidence)
    result = graph.invoke(
        {"status": snapshot["status"], "score": snapshot["score"], "features": snapshot["features"]}
    )
    result["retrieved_ids"] = [item.id for item in result.get("evidence", [])]
    return result


def finish(
    factory: sessionmaker[Session],
    settings: Settings,
    job_id: str,
    token: str,
    result: dict[str, Any],
) -> None:
    with factory.begin() as db:
        job = db.scalar(select(ExplanationJob).where(ExplanationJob.id == job_id).with_for_update())
        if job is None or job.status != "running" or job.lease_token != token:
            return  # A stale worker cannot overwrite a newer lease.
        assessment = db.get(RiskAssessment, job.assessment_id)
        if assessment is None:
            return
        assessment.ai_status = result["ai_status"]
        assessment.prompt_version = PROMPT_VERSION
        # Preserve original deterministic explanation and immutable risk/status history.
        assessment.ai_explanation = result.get("output")
        assessment.retrieved_evidence_ids = result.get("retrieved_ids", [])
        assessment.cited_evidence_ids = (
            result["output"]["evidence_ids"] if result.get("output") else []
        )
        assessment.provider = "gemini" if result["ai_status"] != "disabled" else None
        assessment.model = settings.gemini_model if assessment.provider else None
        job.status = "done" if result["ai_status"] in {"ok", "disabled"} else "failed"
        job.finished_at = utcnow()
        job.error_code = None if job.status == "done" else result["ai_status"]
        assessment.ai_job_status = job.status
        db.add(
            DecisionLog(
                batch_id=assessment.batch_id,
                actor_id=assessment.actor_id,
                decision_type="ai_explanation",
                input_references={
                    "assessment_id": assessment.id,
                    "job_id": job.id,
                    "retrieved_evidence_ids": assessment.retrieved_evidence_ids,
                    "cited_evidence_ids": assessment.cited_evidence_ids,
                    "visited_nodes": result.get("visited", []),
                },
                rationale=f"AI status: {assessment.ai_status}; deterministic result retained",
                policy_version=assessment.workflow_version,
            )
        )


def process_one(
    factory: sessionmaker[Session], settings: Settings, *, assessment_id: str | None = None
) -> bool:
    claimed = claim(factory, settings, assessment_id=assessment_id)
    if claimed is None:
        return False
    job_id, token = claimed
    try:
        result = enrich(factory, settings, job_id)
    except Exception:
        logger.warning("explanation_failed job_id=%s", job_id)
        result = {"ai_status": "failed", "output": None, "retrieved_ids": []}
    finish(factory, settings, job_id, token, result)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Durable optional Gemini explanation worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = Settings()  # type: ignore[call-arg]
    engine = build_engine(settings)
    factory = session_factory(engine)
    try:
        if args.once:
            process_one(factory, settings)
        else:
            while True:
                if not process_one(factory, settings):
                    time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
