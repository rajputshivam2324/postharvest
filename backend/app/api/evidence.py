from fastapi import APIRouter, Depends
from pydantic import Field, HttpUrl
from sqlalchemy.orm import Session

from app.api.dependencies import administrator, current_user
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.time import utcnow
from app.db.models import EvidenceChunk, User
from app.db.session import get_db, get_settings
from app.repositories.common import flush
from app.retrieval.indexing import add_chunk
from app.retrieval.query import EvidenceItem, retrieve
from app.schemas.common import InputSchema
from app.services.resources import audit

router = APIRouter(prefix="/api/v1", tags=["evidence"], dependencies=[Depends(current_user)])


class GuidanceCreate(InputSchema):
    identifier: str = Field(min_length=1, max_length=100)
    commodity: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=6000)
    source_url: HttpUrl
    review_note: str = Field(min_length=1, max_length=500)


@router.post("/guidance", response_model=EvidenceItem, status_code=201)
def guidance(
    payload: GuidanceCreate, db: Session = Depends(get_db), actor: User = Depends(administrator)
) -> EvidenceItem:
    from sqlalchemy import select

    if db.scalar(
        select(EvidenceChunk.id).where(
            EvidenceChunk.source_type == "guidance",
            EvidenceChunk.source_reference == payload.identifier,
        )
    ):
        raise DomainError(409, "conflict", "Guidance identifier already exists")
    chunk = add_chunk(
        db,
        source_type="guidance",
        source_reference=payload.identifier,
        batch_id=None,
        commodity=payload.commodity.lower(),
        text=f"Source: {payload.source_url}\nReview: {payload.review_note}\n{payload.text}",
    )
    audit(db, actor, "guidance_imported", None, {"evidence_id": chunk.id}, payload.review_note)
    flush(db)
    return EvidenceItem(id=chunk.id, source_type=chunk.source_type, text=chunk.text)


@router.get("/batches/{batch_id}/evidence", response_model=list[EvidenceItem])
def evidence(
    batch_id: str,
    db: Session = Depends(get_db),
    actor: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> list[EvidenceItem]:
    return retrieve(db, batch_id=batch_id, actor=actor, at=utcnow(), settings=settings)
