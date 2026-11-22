"""Back-fill one week of SIMULATED monitoring history for a new tomato batch.

Everything is written through the application's own services (device registration,
baseline, observations, risk assessment, alert policy) with the clock set to the time
each record is meant to describe, so the batch ends up with a genuine history: the
assessments, state changes, alerts and priorities are produced by the real rules, not
typed in. Readings are inserted in bulk (one row per five-minute sample) instead of one
HTTP-style ingest call each, which would take hours against a remote database.

The device and every reading carry ``simulated = true``. That flag is part of the data
model and the UI shows it; this script never removes or hides it.

    python -m scripts.seed_week --actor-user-id <operator> [--vendor-user-id <vendor>]
"""

import argparse
import math
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import as_utc, set_clock, utcnow
from app.db.models import Alert, Batch, DecisionLog, SensorReading, User
from app.schemas.resources import BaselineCreate, BatchCreate, DeviceCreate, ObservationCreate
from app.services.assessments import assess
from app.services.resources import (
    audit,
    create_batch,
    record_baseline,
    record_observation,
    register_device,
)
from scripts.climate import IST, box_conditions

STEP = timedelta(minutes=5)
FIRMWARE = "1.4.2"
BASELINE_GAS = 590  # clean-air reference, in line with this board's room-air readings

GAP_START_H, GAP_MINUTES = 60.0, 40  # the sensor loses Wi-Fi and reboots
SUN_LOCAL_START, SUN_MINUTES, SUN_PEAK_RISE = (13, 0), 270, 6.5  # direct sun on the box
SUN_DAY_INDEX = 4  # which local day, counted from the first one in the plan


@dataclass
class Plan:
    """Where the batch's history sits in time and what the staff did during it."""

    start: datetime
    days: int
    seed: int


def hours(plan: Plan, when: datetime) -> float:
    return (when - plan.start).total_seconds() / 3600


def sun_window(plan: Plan) -> tuple[datetime, datetime]:
    """Early on day 5, afternoon sun comes through the window onto the box for a few hours."""
    first_local_day = (plan.start + IST).date()
    local = datetime.combine(
        first_local_day + timedelta(days=SUN_DAY_INDEX), datetime.min.time()
    ) + timedelta(hours=SUN_LOCAL_START[0], minutes=SUN_LOCAL_START[1])
    begin = local.replace(tzinfo=UTC) - IST
    return begin, begin + timedelta(minutes=SUN_MINUTES)


def in_gap(h: float) -> bool:
    return GAP_START_H <= h < GAP_START_H + GAP_MINUTES / 60


def warming_up(h: float, index: int) -> bool:
    after_gap = GAP_START_H + GAP_MINUTES / 60
    return index < 12 or after_gap <= h < after_gap + 0.5


def sun_shape(plan: Plan, tick: datetime) -> float:
    """0..1: how much direct sun is on the box. Ramps up over 40 minutes, holds, fades out."""
    begin, end = sun_window(plan)
    ramp = timedelta(minutes=40)
    if begin <= tick < begin + ramp:
        return (tick - begin) / ramp
    if begin + ramp <= tick < end - ramp:
        return 1.0
    if end - ramp <= tick < end:
        return (end - tick) / ramp
    if end <= tick < end + timedelta(minutes=90):  # the shelf stays warm for a while
        return 0.25 * math.exp(-(tick - end).total_seconds() / 2400)
    return 0.0


def sample(plan: Plan, index: int) -> tuple[datetime, float, float, int, bool]:
    """The reading the sensor takes at tick ``index``: time, C, %RH, raw gas, warming up."""
    rng = random.Random(f"{plan.seed}:{index}")
    tick = plan.start + index * STEP
    h = index * STEP.total_seconds() / 3600
    temperature, humidity = box_conditions(tick, plan.seed)
    # Slow drifts from clouds, people and air currents, on top of the daily cycle.
    phases = random.Random(f"{plan.seed}:phase")
    phase1, phase2 = phases.uniform(0, 6.28), phases.uniform(0, 6.28)
    minutes = index * 5
    temperature += 0.22 * math.sin(2 * math.pi * minutes / 53 + phase1)
    temperature += 0.15 * math.sin(2 * math.pi * minutes / 131 + phase2)
    humidity += 0.8 * math.sin(2 * math.pi * minutes / 71 + phase1)
    sun = sun_shape(plan, tick)
    temperature += SUN_PEAK_RISE * sun
    humidity -= 14 * sun
    temperature += rng.gauss(0, 0.07)
    humidity += rng.gauss(0, 0.35)
    gas = (
        BASELINE_GAS
        + 6
        + 0.30 * h
        + 1.6 * (temperature - 20)
        + 0.35 * (humidity - 50)
        + 90 * sun
        + rng.gauss(0, 5)
    )
    warm = warming_up(h, index)
    if warm:
        gas += 60 * math.exp(-(index % 12) / 4) + rng.gauss(0, 10)
    # The DHT22 reports in tenths; the ADC reports whole counts.
    seconds = rng.uniform(-1, 3)
    return (
        tick + timedelta(seconds=seconds),
        round(temperature, 1),
        round(min(99.9, max(0.0, humidity)), 1),
        max(0, round(gas)),
        warm,
    )


def schedule(plan: Plan, end_hours: float) -> list[float]:
    """Hours at which the monitor assesses the batch: every 3 h, hourly around the sun spell."""
    times = {float(h) for h in range(9, int(end_hours) + 1, 3)}
    begin, end = sun_window(plan)
    first, last = hours(plan, begin), hours(plan, end)
    times |= {float(h) for h in range(int(first) - 1, int(last) + 22)}
    gap_end = GAP_START_H + GAP_MINUTES / 60
    times |= {gap_end + 0.25, gap_end + 0.75, GAP_START_H + 0.5, first + 0.5}
    return sorted(t for t in times if 9 <= t <= end_hours)


def observations(plan: Plan) -> list[tuple[float, dict[str, Any]]]:
    begin, end = sun_window(plan)
    sun_start, sun_end = hours(plan, begin), hours(plan, end)
    return [
        (
            0.2,
            {
                "observation_type": "start_condition",
                "condition": "Roma tomatoes, firm, light red to red",
                "firmness": "firm",
                "visible_mould": False,
                "weight_kg": 18.0,
                "notes": "Box placed on a shelf in the storage room, sensor clipped inside it.",
            },
        ),
        (
            24.5,
            {
                "condition": "Top layer firm, colour even",
                "firmness": "firm",
                "visible_mould": False,
                "weight_kg": 17.9,
            },
        ),
        (
            61.0,
            {
                "condition": "No change in the box",
                "firmness": "firm",
                "visible_mould": False,
                "notes": "Sensor dropped off Wi-Fi for about 40 minutes and rebooted by itself.",
            },
        ),
        (
            sun_start + 2.7,
            {
                "condition": "Afternoon sun came through the window onto the box",
                "notes": "Box moved to the shaded end of the shelf.",
            },
        ),
        (
            sun_end + 20.0,
            {
                "condition": "Top layer slightly soft after the warm afternoon",
                "firmness": "slightly soft",
                "visible_mould": False,
                "weight_kg": 17.6,
            },
        ),
        (
            sun_end + 44.0,
            {
                "condition": "Colour even, firmness normal again",
                "firmness": "firm",
                "visible_mould": False,
                "weight_kg": 17.5,
            },
        ),
        (
            plan.days * 24 - 2.0,
            {
                "condition": "Morning round: no change",
                "firmness": "firm",
                "visible_mould": False,
            },
        ),
    ]


def decisions(plan: Plan) -> list[tuple[float, str, str]]:
    _, end = sun_window(plan)
    after = hours(plan, end)
    return [
        (
            after + 20.3,
            "inspection",
            "Inspected after the warm afternoon. Top layer slightly soft, no visible mould. "
            "Keep monitoring.",
        ),
        (
            after + 21.0,
            "annotation",
            "Box stays at the shaded end of the shelf with an extra check each morning.",
        ),
    ]


def acknowledge_due(db: Session, actor: User, batch_id: str, now: datetime, *, final: bool) -> int:
    """Staff acknowledge each alert 20 to 40 minutes after it was raised."""
    done = 0
    for alert in db.scalars(
        select(Alert).where(Alert.batch_id == batch_id, Alert.acknowledged_at.is_(None))
    ):
        delay = timedelta(minutes=20 if alert.severity == "high" else 40)
        if final or as_utc(alert.created_at) + delay > now:
            continue
        alert.acknowledged_at, alert.acknowledged_by = now, actor.id
        audit(
            db,
            actor,
            "alert_acknowledged",
            alert.batch_id,
            {"alert_id": alert.id},
            "Operator acknowledged the alert; acknowledgement is not resolution",
        )
        done += 1
    return done


def seed_week(
    db: Session,
    actor: User,
    settings: Settings,
    *,
    identifier: str = "TOMATO-BOX-PILOT-3",
    device_identifier: str = "ESP32-24A1604F7B2C",
    days: int = 7,
    seed: int = 579,
    owner_id: str | None = None,
    end: datetime | None = None,
    commit: Callable[[], None] | None = None,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    if db.scalar(select(Batch.id).where(Batch.identifier == identifier)):
        raise SystemExit(f"Batch {identifier} already exists; archive it first or pick another")
    end = (end or utcnow()).replace(second=0, microsecond=0)
    end -= timedelta(minutes=end.minute % 5)
    plan = Plan(start=end - timedelta(days=days), days=days, seed=seed)
    commit = commit or db.commit
    stats: dict[str, Any] = {"readings": 0, "assessments": 0, "alerts_acknowledged": 0}
    try:
        set_clock(plan.start)
        batch = create_batch(
            db,
            BatchCreate(
                identifier=identifier,
                commodity="tomato",
                quantity=18,
                unit="kg",
                storage_location="Storage room, Sector 7, Faridabad",
                notes=(
                    "Roma tomatoes from the morning delivery, one box on a shelf in an "
                    "unheated room, sensor inside."
                ),
                attributes={"simulated": True, "scenario": "week-v2-faridabad", "seed": seed},
                owner_id=owner_id,
            ),
            actor,
        )
        device, _ = register_device(
            db,
            DeviceCreate(
                identifier=device_identifier,
                batch_id=batch.id,
                simulated=True,
                firmware_version=FIRMWARE,
            ),
            actor,
        )
        record_baseline(
            db,
            device.id,
            BaselineCreate(
                gas_adc=BASELINE_GAS,
                recorded_at=plan.start - STEP,
                notes="Clean-air reference taken before the sensor was placed in the box.",
            ),
            actor,
            settings,
        )
        commit()

        pending_obs = sorted(observations(plan), key=lambda item: item[0])
        pending_dec = sorted(decisions(plan), key=lambda item: item[0])
        plan_steps = schedule(plan, days * 24)
        index = 0
        total = days * 24 * 12

        def insert_until(limit: datetime) -> None:
            nonlocal index
            rows = []
            while plan.start + index * STEP <= limit:
                when, temperature, humidity, gas, warm = sample(plan, index)
                h = hours(plan, plan.start + index * STEP)
                index += 1
                if in_gap(h):
                    continue
                rows.append(
                    SensorReading(
                        device_id=device.id,
                        batch_id=batch.id,
                        event_id=f"{device.identifier}-{int(when.timestamp())}",
                        temperature_c=temperature,
                        humidity_pct=humidity,
                        gas_adc=gas,
                        gas_voltage_v=round(gas / 4095 * 3.3, 4),
                        warming_up=warm,
                        simulated=True,
                        firmware_version=FIRMWARE,
                        source_timestamp=when,
                        ingested_at=when + timedelta(seconds=1.2),
                    )
                )
            db.add_all(rows)
            db.flush()
            if rows:
                device.last_seen_at = rows[-1].ingested_at
            stats["readings"] += len(rows)

        def advance(to: datetime, *, final: bool = False) -> None:
            set_clock(to)
            insert_until(to)
            while pending_obs and plan.start + timedelta(hours=pending_obs[0][0]) <= to:
                h, body = pending_obs.pop(0)
                record_observation(
                    db,
                    batch.id,
                    ObservationCreate.model_validate(
                        {"observed_at": plan.start + timedelta(hours=h), **body}
                    ),
                    actor,
                    settings,
                )
            while pending_dec and plan.start + timedelta(hours=pending_dec[0][0]) <= to:
                h, kind, text = pending_dec.pop(0)
                db.add(
                    DecisionLog(
                        batch_id=batch.id,
                        actor_id=actor.id,
                        decision_type=kind,
                        rationale=text,
                        input_references={"override_rank": None},
                        policy_version="inspection-priority-v1",
                        created_at=plan.start + timedelta(hours=h),
                    )
                )
            db.flush()

        historical = settings.model_copy(update={"gemini_api_key": None})
        day_marks = {plan.start + timedelta(days=d) for d in range(1, days + 1)}
        for step in plan_steps:
            when = plan.start + timedelta(hours=step) + timedelta(seconds=20)
            if when > end:
                break
            advance(when)
            assess(db, batch.id, actor, historical)
            stats["assessments"] += 1
            stats["alerts_acknowledged"] += acknowledge_due(db, actor, batch.id, when, final=False)
            if any(abs((when - mark).total_seconds()) < 3 * 3600 for mark in day_marks):
                commit()
                progress(f"  through hour {step:.0f}: {stats}")
        commit()

        # Catch up to the real clock so the latest reading is fresh, then assess once with
        # the real settings (AI explanation queued when a Gemini key is configured).
        set_clock(None)
        now = utcnow()
        insert_until(now)
        while pending_obs:
            h, body = pending_obs.pop(0)
            if plan.start + timedelta(hours=h) <= now:
                record_observation(
                    db,
                    batch.id,
                    ObservationCreate.model_validate(
                        {"observed_at": plan.start + timedelta(hours=h), **body}
                    ),
                    actor,
                    settings,
                )
        db.flush()
        final_assessment = assess(db, batch.id, actor, settings)
        acknowledge_due(db, actor, batch.id, now, final=True)
        commit()
        stats["assessments"] += 1
        stats["batch_id"] = batch.id
        stats["device_id"] = device.id
        stats["final_status"] = final_assessment.status
        stats["final_assessment_id"] = final_assessment.id
        stats["expected_readings"] = total
        return stats
    finally:
        set_clock(None)


def main() -> None:
    from app.db.models import User as UserModel
    from app.db.session import build_engine, session_factory

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--actor-user-id", required=True, help="operator who owns the records")
    parser.add_argument("--vendor-user-id", help="share the batch with this vendor")
    parser.add_argument("--identifier", default="TOMATO-BOX-PILOT-3")
    parser.add_argument("--device-identifier", default="ESP32-24A1604F7B2C")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]  # values come from the environment
    factory = session_factory(build_engine(settings))
    with factory() as db:
        actor = db.scalar(select(UserModel).where(UserModel.user_id == args.actor_user_id))
        if actor is None or actor.role not in {"admin", "operator"} or not actor.active:
            sys.exit("The actor must be an active operator or admin")
        owner = None
        if args.vendor_user_id:
            vendor = db.scalar(select(UserModel).where(UserModel.user_id == args.vendor_user_id))
            if vendor is None or vendor.role != "vendor":
                sys.exit("--vendor-user-id must be an existing vendor")
            owner = vendor.id
        result = seed_week(
            db,
            actor,
            settings,
            identifier=args.identifier,
            device_identifier=args.device_identifier,
            days=args.days,
            owner_id=owner,
        )
    print({k: v for k, v in result.items()})


if __name__ == "__main__":
    main()
