from fastapi import APIRouter, Depends, Response, Security
from fastapi.security import APIKeyHeader
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import get_db, get_settings
from app.schemas.resources import IngestionOut, ReadingCreate
from app.services.ingestion import ingest

# This is the sole device-authenticated endpoint. It does not accept user JWTs.
router = APIRouter(prefix="/api/v1/readings", tags=["device ingestion"])
device_key = APIKeyHeader(name="X-Device-Token", auto_error=False)


@router.post("", response_model=IngestionOut, status_code=201)
def reading(
    payload: ReadingCreate,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    x_device_token: str | None = Security(device_key),
) -> IngestionOut:
    result = ingest(db, payload, x_device_token, settings)
    if result.duplicate:
        response.status_code = 200
    return result
