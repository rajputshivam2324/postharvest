import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Batch, Device, DeviceAssignment, SensorReading, User
from app.repositories.common import accessible_batches, paginate
from app.schemas.common import Page, Pagination
from app.schemas.resources import ReadingPoint, ReadingSeries


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


SERIES_MAX_ROWS = 50_000  # about 170 days of five-minute readings


def reading_series(
    db: Session,
    batch_id: str,
    start: datetime | None,
    end: datetime | None,
    max_points: int,
) -> ReadingSeries:
    """The whole range as at most about ``max_points`` points per device, for charts.

    Paging 200 readings at a time is right for a table but wrong for a chart: a week would
    show only its first 17 hours. When the range holds more readings than ``max_points``
    they are averaged into equal time buckets (per device), so a week is drawn as a week.
    """
    query = select(
        SensorReading.device_id,
        SensorReading.source_timestamp,
        SensorReading.temperature_c,
        SensorReading.humidity_pct,
        SensorReading.gas_adc,
    ).where(SensorReading.batch_id == batch_id)
    if start:
        query = query.where(SensorReading.source_timestamp >= start)
    if end:
        query = query.where(SensorReading.source_timestamp <= end)
    rows = db.execute(
        query.order_by(SensorReading.source_timestamp, SensorReading.id).limit(SERIES_MAX_ROWS + 1)
    ).all()
    if len(rows) > SERIES_MAX_ROWS:
        raise DomainError(422, "range_too_large", "Choose a shorter time range")
    total = len(rows)

    def aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value

    if total <= max_points:
        return ReadingSeries(
            points=[
                ReadingPoint(
                    device_id=r.device_id,
                    source_timestamp=aware(r.source_timestamp),
                    temperature_c=r.temperature_c,
                    humidity_pct=r.humidity_pct,
                    gas_adc=r.gas_adc,
                    samples=1,
                )
                for r in rows
            ],
            total=total,
            bucket_seconds=0,
        )
    first = aware(rows[0].source_timestamp).timestamp()
    last = aware(rows[-1].source_timestamp).timestamp()
    bucket = max(60, math.ceil((last - first) / max_points / 60) * 60)
    groups: dict[tuple[str, int], list[Any]] = defaultdict(list)
    for r in rows:
        groups[
            (r.device_id, int((aware(r.source_timestamp).timestamp() - first) // bucket))
        ].append(r)
    points = []
    for (device_id, _), items in groups.items():
        n = len(items)
        mean_time = sum(aware(i.source_timestamp).timestamp() for i in items) / n
        points.append(
            ReadingPoint(
                device_id=device_id,
                source_timestamp=datetime.fromtimestamp(mean_time, UTC),
                temperature_c=round(sum(i.temperature_c for i in items) / n, 1),
                humidity_pct=round(sum(i.humidity_pct for i in items) / n, 1),
                gas_adc=round(sum(i.gas_adc for i in items) / n),
                samples=n,
            )
        )
    points.sort(key=lambda p: (p.source_timestamp, p.device_id))
    return ReadingSeries(points=points, total=total, bucket_seconds=bucket)
