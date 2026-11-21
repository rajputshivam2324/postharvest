import hashlib
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Batch, EpisodeSummary, EvidenceChunk, Observation, RiskAssessment
from app.repositories.common import flush


def add_chunk(
    db: Session,
    *,
    source_type: str,
    source_reference: str,
    batch_id: str | None,
    commodity: str,
    text: str,
    created_at: datetime | None = None,
) -> EvidenceChunk:
    existing = db.scalar(
        select(EvidenceChunk).where(
            EvidenceChunk.source_type == source_type,
            EvidenceChunk.source_reference == source_reference,
        )
    )
    if existing:
        return existing
    text = text[:8000]
    chunk = EvidenceChunk(
        source_type=source_type,
        source_reference=source_reference,
        batch_id=batch_id,
        commodity=commodity,
        text=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )
    if created_at:
        chunk.created_at = created_at
    db.add(chunk)
    flush(db)
    return chunk


def index_observation(db: Session, batch: Batch, observation: Observation) -> EvidenceChunk:
    text = json.dumps(
        {
            "observation_type": observation.observation_type,
            "condition": observation.condition,
            "firmness": observation.firmness,
            "visible_mould": observation.visible_mould,
            "weight_kg": observation.weight_kg,
            "notes": observation.notes,
            "corrects_id": observation.corrects_id,
            "observed_at": observation.observed_at.isoformat(),
        },
        sort_keys=True,
    )
    return add_chunk(
        db,
        source_type="observation",
        source_reference=observation.id,
        batch_id=batch.id,
        commodity=batch.commodity,
        text=text,
        created_at=observation.created_at,
    )


def index_assessment_inputs(
    db: Session, batch: Batch, assessment: RiskAssessment, episode: EpisodeSummary
) -> None:
    add_chunk(
        db,
        source_type="episode_summary",
        source_reference=episode.id,
        batch_id=batch.id,
        commodity=batch.commodity,
        text=json.dumps(
            {"statistics": episode.statistics, "quality_flags": episode.quality_flags},
            sort_keys=True,
        ),
        created_at=assessment.created_at,
    )
    add_chunk(
        db,
        source_type="past_assessment",
        source_reference=assessment.id,
        batch_id=batch.id,
        commodity=batch.commodity,
        text=json.dumps(
            {
                "status": assessment.status,
                "score": assessment.score,
                "explanation": assessment.explanation,
                "uncertainty": assessment.uncertainty,
                "created_at": assessment.created_at.isoformat(),
            },
            sort_keys=True,
        ),
        created_at=assessment.created_at,
    )
