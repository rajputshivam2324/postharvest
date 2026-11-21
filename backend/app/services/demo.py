"""Explicit, append-only synthetic evidence for exercising the monitoring workflow."""

import random
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.time import utcnow
from app.db.models import RiskAssessment, User
from app.schemas.resources import (
    BaselineCreate,
    BatchCreate,
    DeviceCreate,
    ObservationCreate,
    ReadingCreate,
)
from app.services.assessments import assess
from app.services.ingestion import ingest
from app.services.resources import (
    create_batch,
    record_baseline,
    record_observation,
    register_device,
)


def seed_demo(db: Session, actor: User, settings: Settings) -> tuple[RiskAssessment, int]:
    if actor.role not in {"admin", "operator"} or not actor.active:
        raise DomainError(403, "forbidden", "Operator role required")
    if settings.risk_policy.commodity != "tomato":
        raise DomainError(422, "unsupported_demo_policy", "The demo requires a tomato risk policy")
    now = utcnow()
    run_id = str(uuid4())
    policy = settings.risk_policy
    count = policy.window_seconds // policy.sampling_seconds + 1
    start = now - timedelta(seconds=(count - 1) * policy.sampling_seconds + 1)
    rng = random.Random(42)
    batch = create_batch(
        db,
        BatchCreate(
            identifier=f"DEMO-TOMATO-{run_id[:8]}",
            commodity="tomato",
            quantity=24,
            unit="kg",
            storage_location="Simulation · AI test bay",
            notes=(
                "Synthetic seeded demo only. Rising gas response and environmental exposure "
                "exercise the pipeline; they are not observed spoilage "
                "or validated produce science."
            ),
            attributes={
                "simulated": True,
                "seeded_demo": True,
                "seed": 42,
                "scenario": "rising_response",
                "demo_version": "tomato-ai-demo-v1",
            },
        ),
        actor,
    )
    device, credential = register_device(
        db,
        DeviceCreate(
            identifier=f"DEMO-SENSOR-{run_id[:8]}",
            batch_id=batch.id,
            simulated=True,
            firmware_version="synthetic-demo-v1",
        ),
        actor,
    )
    record_baseline(
        db,
        device.id,
        BaselineCreate(
            gas_adc=1000,
            recorded_at=start - timedelta(seconds=policy.sampling_seconds),
            notes="Synthetic clean-air reference, generated before all demo readings.",
        ),
        actor,
        settings,
    )
    for index in range(count):
        progress = index / (count - 1)
        gas = round(1000 + progress * 1000 + rng.uniform(-4, 4))
        ingest(
            db,
            ReadingCreate(
                device_id=device.id,
                batch_id=batch.id,
                event_id=f"{run_id}:{index}",
                source_timestamp=start + timedelta(seconds=index * policy.sampling_seconds),
                temperature_c=round(27 + progress * 3 + rng.uniform(-0.2, 0.2), 3),
                humidity_pct=round(96 + progress + rng.uniform(-0.2, 0.2), 3),
                gas_adc=gas,
                gas_voltage_v=round(gas / 4095 * 3.3, 4),
                simulated=True,
                firmware_version="synthetic-demo-v1",
            ),
            credential,
            settings,
        )
    for when, kind, condition, notes in [
        (
            start,
            "start_condition",
            "Synthetic starting condition: tomatoes at mixed ripeness.",
            "Generated example, not a physical inspection. Gas rise may reflect ripening "
            "and multiple sensor influences.",
        ),
        (
            start + timedelta(seconds=policy.window_seconds // 2),
            "routine",
            "Synthetic follow-up: softer fruit noted; visible mould not established.",
            "Generated observation for retrieval testing. Request a real human inspection "
            "before any handling decision.",
        ),
    ]:
        record_observation(
            db,
            batch.id,
            ObservationCreate.model_validate(
                {
                    "observation_type": kind,
                    "observed_at": when,
                    "condition": condition,
                    "notes": notes,
                }
            ),
            actor,
            settings,
        )
    assessment = assess(db, batch.id, actor, settings)
    if assessment.score is None:
        raise DomainError(
            422,
            "demo_quality_failed",
            "Configured policy rejected the demo window; no demo records were saved",
        )
    return assessment, count
