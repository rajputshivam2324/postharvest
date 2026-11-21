import secrets
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import current_user, operator
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.security import credential_hash
from app.db.models import (
    Batch,
    Device,
    DeviceAssignment,
    DeviceBaseline,
    Observation,
    SensorReading,
    User,
)
from app.db.session import get_db, get_settings
from app.repositories.common import accessible_batches, flush, paginate, require_batch
from app.repositories.monitoring import device_visibility, reading_history, require_device
from app.schemas.common import Page, Pagination
from app.schemas.pairing import DevicePairingOut, PairingOut
from app.schemas.resources import (
    AssignmentCreate,
    AssignmentOut,
    BaselineCreate,
    BaselineOut,
    BatchCreate,
    BatchOut,
    BatchUpdate,
    CredentialOut,
    DeviceCreate,
    DeviceOut,
    DeviceRegistered,
    DeviceUpdate,
    ObservationCreate,
    ObservationOut,
    ReadingOut,
    RiskStatus,
    VendorOut,
)
from app.services import pairing, resources

router = APIRouter(prefix="/api/v1", tags=["monitoring"], dependencies=[Depends(current_user)])


@router.post("/batches", response_model=BatchOut, status_code=201)
def create_batch(
    payload: BatchCreate, db: Session = Depends(get_db), user: User = Depends(operator)
) -> Batch:
    return resources.create_batch(db, payload, user)


@router.get("/batches", response_model=Page[BatchOut])
def list_batches(
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    commodity: str | None = None,
    storage_location: str | None = None,
    status: RiskStatus | None = None,
    archived: bool = False,
) -> Page:
    query = accessible_batches(user).where(Batch.archived == archived)
    if commodity:
        query = query.where(Batch.commodity == commodity.lower())
    if storage_location:
        query = query.where(Batch.storage_location == storage_location)
    if status:
        query = query.where(Batch.status == status)
    return paginate(db, query.order_by(Batch.created_at.desc(), Batch.id), page)


@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_batch(
    batch_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> Batch:
    return require_batch(db, batch_id, user)


@router.patch("/batches/{batch_id}", response_model=BatchOut)
def update_batch(
    batch_id: str,
    payload: BatchUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(operator),
) -> Batch:
    return resources.update_batch(db, batch_id, payload, user)


@router.post("/batches/{batch_id}/archive", response_model=BatchOut)
def archive_batch(
    batch_id: str, db: Session = Depends(get_db), user: User = Depends(operator)
) -> Batch:
    return resources.archive_batch(db, batch_id, user)


@router.post("/devices", response_model=DeviceRegistered, status_code=201)
def register_device(
    payload: DeviceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(operator),
    settings: Settings = Depends(get_settings),
) -> DeviceRegistered:
    device, credential = resources.register_device(db, payload, user)
    return DeviceRegistered(
        **resources.describe_device(device, settings).model_dump(), credential=credential
    )


@router.post("/devices/pairing", response_model=DevicePairingOut, status_code=201)
def register_device_for_pairing(
    payload: DeviceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(operator),
    settings: Settings = Depends(get_settings),
) -> DevicePairingOut:
    """Register a device without showing a credential; the device claims it with a code."""
    device, code, row = pairing.register_for_pairing(db, payload, user, settings)
    return DevicePairingOut(
        **resources.describe_device(device, settings).model_dump(),
        pairing_code=code,
        pairing_expires_at=row.expires_at,
    )


@router.post("/devices/{device_id}/pairing", response_model=PairingOut, status_code=201)
def new_pairing_code(
    device_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(operator),
    settings: Settings = Depends(get_settings),
) -> PairingOut:
    """Issue a fresh code to (re)pair a device. Its current credential keeps working until
    the new code is claimed."""
    device = require_device(db, device_id, user)
    code, row = pairing.issue_code(db, device, user, settings)
    return PairingOut(device_id=device.id, pairing_code=code, expires_at=row.expires_at)


@router.get("/devices", response_model=Page[DeviceOut])
def list_devices(
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    batch_id: str | None = None,
    unassigned: bool = False,
    settings: Settings = Depends(get_settings),
) -> Page:
    """`batch_id` lists every device that has ever served the batch, not only current ones."""
    query = select(Device)
    allowed = device_visibility(user)
    if allowed is not None:
        query = query.where(Device.id.in_(allowed))
    if batch_id:
        require_batch(db, batch_id, user)
        served = select(DeviceAssignment.device_id).where(DeviceAssignment.batch_id == batch_id)
        query = query.where(Device.id.in_(served))
    if unassigned:
        query = query.where(Device.batch_id.is_(None))
    result = paginate(db, query.order_by(Device.created_at, Device.id), page)
    result.items = [resources.describe_device(device, settings) for device in result.items]
    return result


@router.get("/devices/{device_id}", response_model=DeviceOut)
def get_device(
    device_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> DeviceOut:
    return resources.describe_device(require_device(db, device_id, user), settings)


@router.patch("/devices/{device_id}", response_model=DeviceOut)
def update_device(
    device_id: str,
    payload: DeviceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(operator),
    settings: Settings = Depends(get_settings),
) -> DeviceOut:
    device = require_device(db, device_id, user)
    device.active = payload.active
    resources.audit(
        db,
        user,
        "device_updated",
        device.batch_id,
        {"device_id": device.id},
        "Device active flag updated",
    )
    flush(db)
    return resources.describe_device(device, settings)


@router.post("/devices/{device_id}/rotate-credential", response_model=CredentialOut)
def rotate_credential(
    device_id: str, db: Session = Depends(get_db), user: User = Depends(operator)
) -> CredentialOut:
    device = require_device(db, device_id, user)
    token = secrets.token_urlsafe(32)
    device.credential_hash = credential_hash(token)
    resources.audit(
        db,
        user,
        "device_credential_rotated",
        device.batch_id,
        {"device_id": device.id},
        "Device credential rotated",
    )
    flush(db)
    return CredentialOut(device_id=device.id, credential=token)


@router.post("/devices/{device_id}/assignment", response_model=AssignmentOut)
def assign_device(
    device_id: str,
    payload: AssignmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(operator),
) -> DeviceAssignment:
    device = require_device(db, device_id, user)
    return resources.assign_device(
        db, device, payload.batch_id, user, replace=payload.replace, note=payload.note
    )


@router.delete("/devices/{device_id}/assignment", response_model=DeviceOut)
def release_device(
    device_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(operator),
    settings: Settings = Depends(get_settings),
) -> DeviceOut:
    device = resources.release_device(db, require_device(db, device_id, user), user)
    return resources.describe_device(device, settings)


@router.get("/devices/{device_id}/assignments", response_model=Page[AssignmentOut])
def device_assignments(
    device_id: str,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page:
    require_device(db, device_id, user)
    visible = accessible_batches(user).with_only_columns(Batch.id)
    return paginate(
        db,
        select(DeviceAssignment)
        .where(DeviceAssignment.device_id == device_id, DeviceAssignment.batch_id.in_(visible))
        .order_by(DeviceAssignment.assigned_at.desc(), DeviceAssignment.id),
        page,
    )


@router.get("/devices/{device_id}/readings/latest", response_model=ReadingOut | None)
def latest_device_reading(
    device_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> SensorReading | None:
    """Newest reading from this device, including unattached ones, for setup checks."""
    require_device(db, device_id, user)
    query = select(SensorReading).where(SensorReading.device_id == device_id)
    if user.role == "vendor":
        query = query.where(
            SensorReading.batch_id.in_(accessible_batches(user).with_only_columns(Batch.id))
        )
    return db.scalar(
        query.order_by(SensorReading.source_timestamp.desc(), SensorReading.id.desc()).limit(1)
    )


@router.get("/vendors", response_model=Page[VendorOut])
def list_vendors(
    page: Pagination = Depends(), db: Session = Depends(get_db), _: User = Depends(operator)
) -> Page:
    """Active vendors an operator may share a batch with. Exposes no other user data."""
    return paginate(
        db,
        select(User).where(User.role == "vendor", User.active).order_by(User.user_id, User.id),
        page,
    )


@router.post("/devices/{device_id}/baseline", response_model=BaselineOut, status_code=201)
def baseline(
    device_id: str,
    payload: BaselineCreate,
    db: Session = Depends(get_db),
    user: User = Depends(operator),
    settings: Settings = Depends(get_settings),
) -> DeviceBaseline:
    return resources.record_baseline(db, device_id, payload, user, settings)


@router.get("/devices/{device_id}/baselines", response_model=Page[BaselineOut])
def baselines(
    device_id: str,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page:
    require_device(db, device_id, user)
    return paginate(
        db,
        select(DeviceBaseline)
        .where(DeviceBaseline.device_id == device_id)
        .order_by(DeviceBaseline.recorded_at.desc(), DeviceBaseline.id),
        page,
    )


def validate_time_range(start: datetime | None, end: datetime | None) -> None:
    if start and end and start > end:
        raise DomainError(422, "invalid_time_range", "Start must precede end")


@router.get("/batches/{batch_id}/readings", response_model=Page[ReadingOut])
def readings(
    batch_id: str,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    start: Annotated[AwareDatetime | None, Query()] = None,
    end: Annotated[AwareDatetime | None, Query()] = None,
) -> Page:
    require_batch(db, batch_id, user)
    validate_time_range(start, end)
    return reading_history(db, batch_id, page, start, end)


@router.get("/batches/{batch_id}/readings/latest", response_model=ReadingOut | None)
def latest_reading(
    batch_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)
) -> SensorReading | None:
    require_batch(db, batch_id, user)
    return db.scalar(
        select(SensorReading)
        .where(SensorReading.batch_id == batch_id)
        .order_by(SensorReading.source_timestamp.desc(), SensorReading.id.desc())
        .limit(1)
    )


@router.post("/batches/{batch_id}/observations", response_model=ObservationOut, status_code=201)
def observe(
    batch_id: str,
    payload: ObservationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(operator),
    settings: Settings = Depends(get_settings),
) -> Observation:
    return resources.record_observation(db, batch_id, payload, user, settings)


@router.get("/batches/{batch_id}/observations", response_model=Page[ObservationOut])
def observations(
    batch_id: str,
    page: Pagination = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Page:
    require_batch(db, batch_id, user)
    return paginate(
        db,
        select(Observation)
        .where(Observation.batch_id == batch_id)
        .order_by(Observation.observed_at.desc(), Observation.id),
        page,
    )
