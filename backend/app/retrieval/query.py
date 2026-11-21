import json
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import EvidenceChunk, User
from app.repositories.common import require_batch


class EvidenceItem(BaseModel):
    id: str
    source_type: str
    text: str


def scoped_query(db: Session, batch_id: str, actor: User, at: datetime) -> Select[Any]:
    batch = require_batch(db, batch_id, actor)
    return select(EvidenceChunk).where(
        or_(
            EvidenceChunk.batch_id == batch_id,
            and_(
                EvidenceChunk.batch_id.is_(None),
                EvidenceChunk.source_type == "guidance",
                EvidenceChunk.commodity == batch.commodity,
            ),
        ),
        EvidenceChunk.created_at <= at,
        # Starting-condition observations/guidance remain relevant outside the recent window.
        or_(
            EvidenceChunk.source_type.in_(["guidance", "observation"]),
            EvidenceChunk.created_at >= at - timedelta(days=30),
        ),
    )


def retrieve(
    db: Session,
    *,
    batch_id: str,
    actor: User,
    at: datetime,
    settings: Settings,
    query_embedding: list[float] | None = None,
    exclude_assessment_id: str | None = None,
) -> list[EvidenceItem]:
    query = scoped_query(db, batch_id, actor, at)
    if exclude_assessment_id:
        query = query.where(
            or_(
                EvidenceChunk.source_type != "past_assessment",
                EvidenceChunk.source_reference != exclude_assessment_id,
            )
        )
    rows: list[EvidenceChunk] = []
    if query_embedding is not None and db.get_bind().dialect.name == "postgresql":
        vector_query = query.where(
            EvidenceChunk.embedding.is_not(None),
            EvidenceChunk.embedding_model == settings.gemini_embedding_model,
        )
        rows = list(
            db.scalars(
                vector_query.order_by(
                    EvidenceChunk.embedding.cosine_distance(query_embedding), EvidenceChunk.id
                ).limit(settings.retrieval_top_k)
            )
        )
    # Always retain a structured fallback; vector availability must not hide unembedded evidence.
    recent = list(
        db.scalars(
            query.order_by(EvidenceChunk.created_at.desc(), EvidenceChunk.id).limit(
                settings.retrieval_top_k * 4
            )
        )
    )
    unique = {row.id for row in rows}
    rows.extend(row for row in recent if row.id not in unique)
    # Bound serialized bytes, including IDs/types/JSON escaping. This is a conservative
    # token-budget upper bound without an external tokenizer or a paid count-tokens call.
    budget = settings.retrieval_token_budget
    items: list[EvidenceItem] = []
    for row in rows:
        if len(items) >= settings.retrieval_top_k or budget <= 0:
            break
        item = EvidenceItem(id=row.id, source_type=row.source_type, text="")
        overhead = len(json.dumps(item.model_dump()).encode()) + 2
        if budget <= overhead:
            continue
        text = row.text[: budget - overhead]
        while len(json.dumps({**item.model_dump(), "text": text}).encode()) + 2 > budget:
            text = text[: max(0, len(text) - max(1, len(text) // 10))]
        item.text = text
        items.append(item)
        budget -= len(json.dumps(item.model_dump()).encode()) + 2
    return items
