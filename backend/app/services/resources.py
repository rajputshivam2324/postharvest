import secrets
from datetime import timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.security import credential_hash
from app.core.time import as_utc, utcnow
from app.db.models import (
    Batch,
    DecisionLog,
    Device,
    DeviceAssignment,
    DeviceBaseline,
    Observation,
    User,
)
from app.repositories.common import flush, require_batch
from app.repositories.monitoring import require_device
from app.schemas.resources import (
    BaselineCreate,
    BatchCreate,
    BatchUpdate,
    DeviceCreate,
    DeviceOut,
    ObservationCreate,
)


def audit(
    db: Session, actor: User, kind: str, batch_id: str | None, references: dict, rationale: str
) -> None:
    db.add(
        DecisionLog(
            actor_id=actor.id,
            batch_id=batch_id,
            decision_type=kind,
            input_references=references,
            rationale=rationale,
        )
    )


def check_owner(db: Session, owner_id: str, actor: User) -> None:
    """Admins may hand a batch to any active user; operators only share it with a vendor."""
    owner = db.get(User, owner_id)
    if actor.role != "admin" and owner_id != actor.id:
        if owner is None or owner.role != "vendor" or not owner.active:
            raise DomainError(
                403, "forbidden", "Operators can only share a batch with an active vendor"
            )
    if owner is None or not owner.active:
        raise DomainError(422, "invalid_owner", "Owner must be an active user")


def create_batch(db: Session, payload: BatchCreate, actor: User) -> Batch:
    owner_id = payload.owner_id or actor.id
    check_owner(db, owner_id, actor)
    values = payload.model_dump(exclude={"owner_id"})
    values["commodity"] = payload.commodity.lower()
    batch = Batch(**values, owner_id=owner_id)
    db.add(batch)
    flush(db)
    audit(db, actor, "batch_created", batch.id, {"batch_id": batch.id}, "Batch registered")
    flush(db)
    return batch


def update_batch(db: Session, batch_id: str, payload: BatchUpdate, actor: User) -> Batch:
    batch = require_batch(db, batch_id, actor, writable=True)
    if payload.owner_id is not None:
        check_owner(db, payload.owner_id, actor)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(batch, key, value)
    audit(
        db,
        actor,
        "batch_updated",
        batch.id,
        {"fields": sorted(payload.model_fields_set)},
        "Batch metadata updated",
    )
    flush(db)
    return batch


def archive_batch(db: Session, batch_id: str, actor: User) -> Batch:
    batch = require_batch(db, batch_id, actor)
    if not batch.archived:
        batch.archived = True
        audit(db, actor, "batch_archived", batch.id, {}, "Batch archived; history retained")
        flush(db)
        # Archived batches are read-only, so their hardware is freed for the next batch.
        for assignment in open_assignments(db, batch_id=batch.id):
            release_assignment(db, assignment, actor, "Released when the batch was archived")
    return batch


def open_assignments(
    db: Session, *, batch_id: str | None = None, device_id: str | None = None
) -> list[DeviceAssignment]:
    query = select(DeviceAssignment).where(DeviceAssignment.released_at.is_(None))
    if batch_id is not None:
        query = query.where(DeviceAssignment.batch_id == batch_id)
    if device_id is not None:
        query = query.where(DeviceAssignment.device_id == device_id)
    return list(db.scalars(query.order_by(DeviceAssignment.assigned_at, DeviceAssignment.id)))


def release_assignment(db: Session, assignment: DeviceAssignment, actor: User, reason: str) -> None:
    """Close an assignment. History is kept; only the device's current pointer is cleared."""
    assignment.released_at = utcnow()
    assignment.released_by = actor.id
    assignment.note = reason if not assignment.note else f"{assignment.note}; {reason}"[:500]
    device = db.get(Device, assignment.device_id)
    if device is not None and device.batch_id == assignment.batch_id:
        device.batch_id = None
    audit(
        db,
        actor,
        "device_released",
        assignment.batch_id,
        {"device_id": assignment.device_id, "assignment_id": assignment.id},
        reason,
    )
    flush(db)


def assign_device(
    db: Session,
    device: Device,
    batch_id: str,
    actor: User,
    *,
    replace: bool = False,
    note: str | None = None,
) -> DeviceAssignment:
    """Point a device at a batch. Readings already stored never change batch."""
    if not device.active:
        raise DomainError(409, "device_disabled", "Enable the device before assigning it")
    batch = require_batch(db, batch_id, actor, writable=True)
    for current in open_assignments(db, device_id=device.id):
        if current.batch_id == batch.id:
            return current
        if not replace:
            raise DomainError(
                409,
                "device_assigned",
                "Device is serving another batch; release it first or confirm the move",
            )
        release_assignment(db, current, actor, "Moved to another batch")
    assignment = DeviceAssignment(
        device_id=device.id, batch_id=batch.id, assigned_by=actor.id, note=note
    )
    db.add(assignment)
    device.batch_id = batch.id
    flush(db)
    audit(
        db,
        actor,
        "device_assigned",
        batch.id,
        {"device_id": device.id, "assignment_id": assignment.id},
        "Device assigned to batch",
    )
    flush(db)
    return assignment


def release_device(db: Session, device: Device, actor: User) -> Device:
    for current in open_assignments(db, device_id=device.id):
        release_assignment(db, current, actor, "Released by an operator")
    return device


def register_device(
    db: Session, payload: DeviceCreate, actor: User, *, paired: bool = True
) -> tuple[Device, str]:
    """Create a device. With paired=False it gets no usable credential until it claims a
    pairing code; the returned token is then a throwaway nobody knows."""
    if payload.batch_id:
        require_batch(db, payload.batch_id, actor, writable=True)
    token = secrets.token_urlsafe(32)
    device = Device(
        **payload.model_dump(exclude={"batch_id"}),
        credential_hash=credential_hash(token),
        paired_at=utcnow() if paired else None,
    )
    db.add(device)
    flush(db)
    audit(
        db,
        actor,
        "device_registered",
        None,
        {"device_id": device.id},
        "Device registered with a one-time credential"
        if paired
        else "Device registered; waiting to be paired with a one-time code",
    )
    flush(db)
    if payload.batch_id:
        assign_device(db, device, payload.batch_id, actor)
    return device, token


def describe_device(device: Device, settings: Settings) -> DeviceOut:
    status: Literal["disabled", "unpaired", "never_seen", "online", "stale"] = "never_seen"
    if not device.active:
        status = "disabled"
    elif device.paired_at is None:
        status = "unpaired"
    elif device.last_seen_at:
        status = (
            "stale"
            if (utcnow() - as_utc(device.last_seen_at)).total_seconds()
            > settings.device_stale_seconds
            else "online"
        )
    return DeviceOut(
        **{
            column.name: getattr(device, column.name)
            for column in Device.__table__.columns
            if column.name != "credential_hash"
        },
        connection_status=status,
    )


def record_baseline(
    db: Session, device_id: str, payload: BaselineCreate, actor: User, settings: Settings
) -> DeviceBaseline:
    device = require_device(db, device_id, actor)
    # A clean-air baseline is taken before a device joins a batch, so unassigned is fine.
    if device.batch_id is not None:
        require_batch(db, device.batch_id, actor, writable=True)
    if as_utc(payload.recorded_at) > utcnow() + timedelta(seconds=settings.max_future_seconds):
        raise DomainError(422, "future_timestamp", "Baseline timestamp is in the future")
    baseline = DeviceBaseline(**payload.model_dump(), device_id=device.id, actor_id=actor.id)
    db.add(baseline)
    flush(db)
    audit(
        db,
        actor,
        "baseline_recorded",
        device.batch_id,
        {"baseline_id": baseline.id},
        "Clean-air raw gas baseline recorded",
    )
    flush(db)
    return baseline


def record_observation(
    db: Session, batch_id: str, payload: ObservationCreate, actor: User, settings: Settings
) -> Observation:
    require_batch(db, batch_id, actor, writable=True)
    if as_utc(payload.observed_at) > utcnow() + timedelta(seconds=settings.max_future_seconds):
        raise DomainError(422, "future_timestamp", "Observation timestamp is in the future")
    if payload.corrects_id:
        original = db.get(Observation, payload.corrects_id)
        if original is None or original.batch_id != batch_id:
            raise DomainError(422, "invalid_correction", "Correction must reference this batch")
    observation = Observation(**payload.model_dump(), batch_id=batch_id, observer_id=actor.id)
    db.add(observation)
    flush(db)
    audit(
        db,
        actor,
        "observation_recorded",
        batch_id,
        {"observation_id": observation.id},
        "Append-only operator observation",
    )
    from app.retrieval.indexing import index_observation

    index_observation(db, require_batch(db, batch_id, actor), observation)
    flush(db)
    return observation
