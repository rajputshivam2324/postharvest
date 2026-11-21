from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Device, DeviceAssignment, DeviceBaseline, RiskAssessment, SensorReading
from app.risk.engine import Baseline, Sample


def load_window(
    db: Session, batch_id: str, start: datetime, end: datetime
) -> tuple[list[Sample], list[Baseline], list[str]]:
    # Use assignment history, not the device's current batch: devices that have since
    # moved on must still contribute the readings they took for this batch.
    served = select(DeviceAssignment.device_id).where(DeviceAssignment.batch_id == batch_id)
    devices = list(db.scalars(select(Device.id).where(Device.id.in_(served), Device.active)))
    rows = list(
        db.scalars(
            select(SensorReading)
            .where(
                SensorReading.batch_id == batch_id,
                SensorReading.device_id.in_(devices),
                SensorReading.source_timestamp >= start,
                SensorReading.source_timestamp <= end,
            )
            .order_by(SensorReading.source_timestamp, SensorReading.id)
        )
    )
    samples = [
        Sample(
            r.id,
            r.device_id,
            r.source_timestamp,
            r.temperature_c,
            r.humidity_pct,
            r.gas_adc,
            r.warming_up,
            r.simulated,
        )
        for r in rows
    ]
    raw = list(
        db.scalars(
            select(DeviceBaseline)
            .where(DeviceBaseline.device_id.in_(devices), DeviceBaseline.recorded_at <= end)
            .order_by(DeviceBaseline.recorded_at, DeviceBaseline.id)
        )
    )
    baselines = [Baseline(b.id, b.device_id, b.recorded_at, b.gas_adc) for b in raw]
    return samples, baselines, sorted(devices)


def latest_assessment(db: Session, batch_id: str) -> RiskAssessment | None:
    return db.scalar(
        select(RiskAssessment)
        .where(RiskAssessment.batch_id == batch_id)
        .order_by(RiskAssessment.created_at.desc(), RiskAssessment.id.desc())
        .limit(1)
    )
