from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Batch, Device, DeviceAssignment, SensorReading, User
from app.repositories.common import accessible_batches, paginate
from app.schemas.common import Page, Pagination


def device_visibility(user: User) -> Select[tuple[str]] | None:
    """Device ids a user may see, or None when they may see every device.

    Vendors see only devices that have served one of their batches, past or present.
    Operators and admins also see unassigned devices, which they need in order to set up.
    """
    if user.role != "vendor":
        return None
    visible = accessible_batches(user).with_only_columns(Batch.id)
    return select(DeviceAssignment.device_id).where(DeviceAssignment.batch_id.in_(visible))


def require_device(db: Session, device_id: str, user: User) -> Device:
    query = select(Device).where(Device.id == device_id)
    allowed = device_visibility(user)
    if allowed is not None:
        query = query.where(Device.id.in_(allowed))
    device = db.scalar(query)
    if device is None:
        raise DomainError(404, "not_found", "Device not found")
    return device


def existing_event(db: Session, device_id: str, event_id: str | None) -> SensorReading | None:
    if event_id is None:
        return None
    return db.scalar(
        select(SensorReading).where(
            SensorReading.device_id == device_id, SensorReading.event_id == event_id
        )
    )


def reading_history(
    db: Session, batch_id: str, page: Pagination, start: datetime | None, end: datetime | None
) -> Page:
    query = select(SensorReading).where(SensorReading.batch_id == batch_id)
    if start:
        query = query.where(SensorReading.source_timestamp >= start)
    if end:
        query = query.where(SensorReading.source_timestamp <= end)
    return paginate(db, query.order_by(SensorReading.source_timestamp, SensorReading.id), page)
