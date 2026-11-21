from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import operator
from app.core.config import Settings
from app.db.models import Batch, User
from app.db.session import get_db, get_settings
from app.schemas.demo import DemoBatchOut
from app.schemas.operations import AssessmentOut
from app.schemas.resources import BatchOut
from app.services.demo import seed_demo

router = APIRouter(prefix="/api/v1/demo", tags=["synthetic demo"])


@router.post("/batches", response_model=DemoBatchOut, status_code=201)
def create_demo_batch(
    db: Session = Depends(get_db),
    actor: User = Depends(operator),
    settings: Settings = Depends(get_settings),
) -> DemoBatchOut:
    assessment, count = seed_demo(db, actor, settings)
    batch = db.get(Batch, assessment.batch_id)
    return DemoBatchOut(
        batch=BatchOut.model_validate(batch),
        assessment=AssessmentOut.model_validate(assessment),
        reading_count=count,
    )
