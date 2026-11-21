"""Keep the SIMULATED sensor from scripts/seed_week.py reporting every five minutes.

Each reading goes through the application's real ingestion service, so the device shows
as online, the monitor (`python -m app.monitor`) assesses fresh data, and alerts and
priorities move as they would with hardware. Stopping this script is a real outage: the
device goes stale and the monitor raises the matching alert. Readings stay flagged
simulated.

    python -m scripts.live_feed --device-identifier ESP32-24A1604F7B2C
"""

import argparse
import secrets
import sys
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import credential_hash
from app.core.time import as_utc, utcnow
from app.db.models import Batch, Device, User
from app.schemas.resources import ReadingCreate
from app.services.ingestion import ingest
from app.services.resources import audit
from scripts.seed_week import FIRMWARE, STEP, Plan, sample


def feed_once(
    db: Session, settings: Settings, device_identifier: str, actor: User, token: str | None = None
) -> tuple[str, bool]:
    """Send the reading for the current five-minute tick. Returns (token, duplicate)."""
    device = db.scalar(select(Device).where(Device.identifier == device_identifier))
    if device is None or not device.simulated or device.batch_id is None:
        raise SystemExit("Not an assigned simulated device")
    batch = db.get(Batch, device.batch_id)
    if batch is None or "seed" not in batch.attributes:
        raise SystemExit("This device's batch was not created by seed_week")
    if token is None:
        # Only a hash is stored, so a running feed takes over the credential (and audits it).
        token = secrets.token_urlsafe(32)
        device.credential_hash = credential_hash(token)
        audit(
            db,
            actor,
            "device_credential_rotated",
            device.batch_id,
            {"device_id": device.id},
            "Credential rotated for the simulated live feed",
        )
    seed = batch.attributes["seed"]
    plan = Plan(
        start=as_utc(batch.created_at), days=7, seed=int(seed) if isinstance(seed, int) else 0
    )
    index = int((utcnow() - plan.start) / STEP)
    when, temperature, humidity, gas, warm = sample(plan, index)
    result = ingest(
        db,
        ReadingCreate(
            device_id=device.id,
            event_id=f"{device.identifier}-{int(when.timestamp())}",
            temperature_c=temperature,
            humidity_pct=humidity,
            gas_adc=gas,
            gas_voltage_v=round(gas / 4095 * 3.3, 4),
            warming_up=warm,
            simulated=True,
            firmware_version=FIRMWARE,
            source_timestamp=when,
        ),
        token,
        settings,
    )
    return token, result.duplicate


def seconds_to_next_tick(now: datetime) -> float:
    minutes = 5 - (now.minute % 5)
    nxt = (now + timedelta(minutes=minutes)).replace(second=2, microsecond=0)
    return max(1.0, (nxt - now).total_seconds())


def main() -> None:
    from app.db.session import build_engine, session_factory

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device-identifier", default="ESP32-24A1604F7B2C")
    parser.add_argument("--actor-user-id", required=True, help="operator recorded in the audit")
    parser.add_argument("--once", action="store_true", help="send the current tick and exit")
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]  # values come from the environment
    factory = session_factory(build_engine(settings))
    token: str | None = None
    while True:
        with factory.begin() as db:
            actor = db.scalar(select(User).where(User.user_id == args.actor_user_id))
            if actor is None or actor.role not in {"admin", "operator"} or not actor.active:
                sys.exit("The actor must be an active operator or admin")
            token, duplicate = feed_once(db, settings, args.device_identifier, actor, token)
        print(f"{utcnow():%H:%M:%S} reading {'repeated' if duplicate else 'sent'}", flush=True)
        if args.once:
            return
        time.sleep(seconds_to_next_tick(utcnow()))


if __name__ == "__main__":
    main()
