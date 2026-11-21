"""Pairing: how a new ESP32 gets its credential without anyone copying UUIDs.

An operator registers the device and gets a short single-use code. The device sends that code
to the unauthenticated claim endpoint and receives its permanent credential once. Until then
(and while a replacement code is outstanding) nothing about the device's existing access
changes, so re-pairing a working device causes no downtime.
"""

import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.security import (
    credential_hash,
    new_pairing_code,
    normalize_pairing_code,
    pairing_code_hash,
)
from app.core.time import as_utc, utcnow
from app.db.models import DecisionLog, Device, PairingCode, User
from app.repositories.common import flush
from app.schemas.pairing import PairingClaimed
from app.schemas.resources import DeviceCreate
from app.services.resources import audit, register_device

INVALID = DomainError(404, "invalid_pairing_code", "This code is not valid or has expired")


def issue_code(
    db: Session, device: Device, actor: User, settings: Settings
) -> tuple[str, PairingCode]:
    if not device.active:
        raise DomainError(409, "device_disabled", "Enable the device before pairing it")
    now = utcnow()
    # Only the newest code works: a code that was shown on an old screen must not.
    for old in db.scalars(
        select(PairingCode).where(
            PairingCode.device_id == device.id,
            PairingCode.claimed_at.is_(None),
            PairingCode.expires_at > now,
        )
    ):
        old.expires_at = now
    code = new_pairing_code()
    row = PairingCode(
        device_id=device.id,
        code_hash=pairing_code_hash(code, settings),
        created_by=actor.id,
        expires_at=now + timedelta(seconds=settings.pairing_ttl_seconds),
    )
    db.add(row)
    flush(db)
    audit(
        db,
        actor,
        "device_pairing_issued",
        device.batch_id,
        {"device_id": device.id, "pairing_code_id": row.id},
        "Single-use pairing code issued",
    )
    flush(db)
    return f"{code[:4]}-{code[4:]}", row  # shown as ABCD-EFGH; claiming ignores the hyphen


def register_for_pairing(
    db: Session, payload: DeviceCreate, actor: User, settings: Settings
) -> tuple[Device, str, PairingCode]:
    device, _discarded = register_device(db, payload, actor, paired=False)
    code, row = issue_code(db, device, actor, settings)
    return device, code, row


def claim(db: Session, raw_code: str, settings: Settings) -> PairingClaimed:
    """Exchange a code for the device credential. Every failure looks the same."""
    code = normalize_pairing_code(raw_code)
    if code is None:
        raise INVALID
    row = db.scalar(
        select(PairingCode)
        .where(PairingCode.code_hash == pairing_code_hash(code, settings))
        .with_for_update()
    )
    now = utcnow()
    if row is None or row.claimed_at is not None or as_utc(row.expires_at) <= now:
        raise INVALID
    device = db.scalar(select(Device).where(Device.id == row.device_id).with_for_update())
    if device is None or not device.active:
        raise INVALID
    token = secrets.token_urlsafe(32)
    device.credential_hash = credential_hash(token)
    device.paired_at = now
    row.claimed_at = now
    db.add(
        DecisionLog(
            batch_id=device.batch_id,
            actor_id=None,
            decision_type="device_paired",
            input_references={"device_id": device.id, "pairing_code_id": row.id},
            rationale="Device claimed its credential with a pairing code",
        )
    )
    flush(db)
    return PairingClaimed(
        device_id=device.id,
        identifier=device.identifier,
        credential=token,
        simulated=device.simulated,
        sampling_seconds=settings.risk_policy.sampling_seconds,
    )
