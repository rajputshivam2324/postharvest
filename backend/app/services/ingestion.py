from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.security import verify_credential
from app.core.time import as_utc, utcnow
from app.db.models import Batch, Device, SensorReading
from app.repositories.monitoring import existing_event
from app.schemas.resources import IngestionOut, ReadingCreate, ReadingOut

STALE_BATCH_NOTICE = (
    "The batch_id in the payload differs from the device's current assignment and was "
    "ignored. Remove batch_id from the firmware; the server decides the batch."
)
UNASSIGNED_NOTICE = "Device is not assigned to a batch; the reading was stored unattached."


def replay(existing: SensorReading, payload: ReadingCreate, notice: str | None) -> IngestionOut:
    # batch_id is server-derived, so a retry is compared on the measurement fields only.
    for key, value in payload.model_dump(exclude={"batch_id"}).items():
        stored = getattr(existing, key)
        if key == "source_timestamp":
            stored, value = as_utc(stored), as_utc(value)
        if stored != value:
            raise DomainError(
                409, "event_conflict", "Event ID was already used for another payload"
            )
    return IngestionOut(reading=ReadingOut.model_validate(existing), duplicate=True, notice=notice)


def ingest(
    db: Session, payload: ReadingCreate, token: str | None, settings: Settings
) -> IngestionOut:
    device = db.scalar(select(Device).where(Device.id == payload.device_id).with_for_update())
    if (
        device is None
        or not token
        or not device.active
        or device.paired_at is None
        or not verify_credential(token, device.credential_hash)
    ):
        raise DomainError(401, "invalid_device", "Invalid device credentials")
    # The server decides the batch from the device's assignment. Older firmware still
    # sends batch_id; a stale value is reported, not rejected, so readings are never lost.
    notice = None
    if device.batch_id is None:
        notice = UNASSIGNED_NOTICE
    elif payload.batch_id is not None and payload.batch_id != device.batch_id:
        notice = STALE_BATCH_NOTICE
    if device.simulated != payload.simulated:
        raise DomainError(422, "source_mismatch", "Simulation flag must match registered device")
    existing = existing_event(db, device.id, payload.event_id)
    if existing:
        result = replay(existing, payload, notice)
        device.last_seen_at = utcnow()
        db.flush()
        return result
    if device.batch_id is not None:
        batch = db.scalar(select(Batch).where(Batch.id == device.batch_id).with_for_update())
        if batch is None or batch.archived:
            raise DomainError(409, "batch_archived", "Batch is unavailable for new readings")
    now = utcnow()
    source = as_utc(payload.source_timestamp)
    if source > now + timedelta(seconds=settings.max_future_seconds):
        raise DomainError(422, "future_timestamp", "Source timestamp is too far in the future")
    if source < now - timedelta(days=settings.max_history_days):
        raise DomainError(422, "old_timestamp", "Source timestamp exceeds accepted history")
    reading = SensorReading(
        **payload.model_dump(exclude={"batch_id"}), batch_id=device.batch_id, ingested_at=now
    )
    try:
        with db.begin_nested():
            db.add(reading)
            db.flush()
    except IntegrityError:
        existing = existing_event(db, device.id, payload.event_id)
        if existing:
            result = replay(existing, payload, notice)
            device.last_seen_at = now
            db.flush()
            return result
        raise DomainError(409, "conflict", "Reading conflicts with existing data") from None
    device.last_seen_at = now
    device.firmware_version = payload.firmware_version or device.firmware_version
    db.flush()
    return IngestionOut(reading=ReadingOut.model_validate(reading), duplicate=False, notice=notice)
