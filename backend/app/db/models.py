from datetime import datetime
from typing import Any
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.db.base import Base


def new_id() -> str:
    return str(uuid4())


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('admin','operator','vendor')", name="role"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="operator")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Batch(Base):
    __tablename__ = "batches"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint(
            "status IN ('unknown','fresh','early_decay','spoiling','insufficient_data')",
            name="status",
        ),
        Index("ix_batches_owner_archived", "owner_id", "archived"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identifier: Mapped[str] = mapped_column(String(100), unique=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    commodity: Mapped[str] = mapped_column(String(80), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    storage_location: Mapped[str] = mapped_column(String(200), index=True)
    notes: Mapped[str | None] = mapped_column(String(2000))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="unknown", index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_status: Mapped[str | None] = mapped_column(String(30))
    recovery_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_assessment_signature: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class DecisionLog(Base):
    __tablename__ = "decision_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    decision_type: Mapped[str] = mapped_column(String(80))
    input_references: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rationale: Mapped[str] = mapped_column(String(4000))
    policy_version: Mapped[str] = mapped_column(String(60), default="operations-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    identifier: Mapped[str] = mapped_column(String(100), unique=True)
    # Current assignment only (NULL = unassigned). The full history lives in
    # device_assignments; both are changed together by services.devices.
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"), index=True)
    credential_hash: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    firmware_version: Mapped[str | None] = mapped_column(String(80))
    # NULL until the device has received its credential (shown at registration, or claimed
    # with a pairing code). An unpaired device cannot authenticate.
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PairingCode(Base):
    """A short-lived, single-use code that lets one physical device fetch its credential."""

    __tablename__ = "pairing_codes"
    __table_args__ = (Index("ix_pairing_device", "device_id", "created_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    # Keyed HMAC of the code (see core.security.pairing_code_hash); never the code itself.
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeviceAssignment(Base):
    """Append-only record of which batch a device served and when."""

    __tablename__ = "device_assignments"
    __table_args__ = (
        Index("ix_assignments_device_time", "device_id", "assigned_at"),
        Index("ix_assignments_batch", "batch_id"),
        Index(
            "uq_assignment_open_device",
            "device_id",
            unique=True,
            postgresql_where=text("released_at IS NULL"),
            sqlite_where=text("released_at IS NULL"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"))
    assigned_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(String(500))


class DeviceBaseline(Base):
    __tablename__ = "device_baselines"
    __table_args__ = (
        CheckConstraint("gas_adc > 0 AND gas_adc <= 4095", name="gas_adc"),
        Index("ix_baselines_device_time", "device_id", "recorded_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    gas_adc: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SensorReading(Base):
    __tablename__ = "sensor_readings"
    __table_args__ = (
        UniqueConstraint("device_id", "event_id"),
        CheckConstraint("temperature_c >= -40 AND temperature_c <= 80", name="temperature"),
        CheckConstraint("humidity_pct >= 0 AND humidity_pct <= 100", name="humidity"),
        CheckConstraint("gas_adc >= 0 AND gas_adc <= 4095", name="gas_adc"),
        CheckConstraint("gas_voltage_v >= 0 AND gas_voltage_v <= 3.3", name="gas_voltage"),
        Index("ix_readings_batch_time", "batch_id", "source_timestamp", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"))
    # NULL = the device was unassigned when this reading arrived. Such readings are
    # kept for connectivity checks but are never attached to a batch afterwards.
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"))
    event_id: Mapped[str | None] = mapped_column(String(150))
    temperature_c: Mapped[float] = mapped_column(Float)
    humidity_pct: Mapped[float] = mapped_column(Float)
    gas_adc: Mapped[int] = mapped_column(Integer)
    gas_voltage_v: Mapped[float] = mapped_column(Float)
    warming_up: Mapped[bool] = mapped_column(Boolean, default=False)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    firmware_version: Mapped[str | None] = mapped_column(String(80))
    source_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        CheckConstraint(
            "observation_type IN ('routine','start_condition','final_outcome','correction')",
            name="observation_type",
        ),
        CheckConstraint("weight_kg IS NULL OR weight_kg >= 0", name="weight"),
        Index("ix_observations_batch_time", "batch_id", "observed_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"))
    observer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    observation_type: Mapped[str] = mapped_column(String(30))
    condition: Mapped[str] = mapped_column(String(500))
    firmness: Mapped[str | None] = mapped_column(String(100))
    visible_mould: Mapped[bool | None] = mapped_column(Boolean)
    weight_kg: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(String(2000))
    photo_reference: Mapped[str | None] = mapped_column(String(500))
    corrects_id: Mapped[str | None] = mapped_column(ForeignKey("observations.id"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EpisodeSummary(Base):
    __tablename__ = "episode_summaries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window_seconds: Mapped[int] = mapped_column(Integer)
    statistics: Mapped[dict[str, Any]] = mapped_column(JSON)
    quality_flags: Mapped[list[str]] = mapped_column(JSON)
    engine_version: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"
    __table_args__ = (
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 100)", name="score"),
        Index("ix_assessments_batch_time", "batch_id", "created_at", "id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    episode_id: Mapped[str] = mapped_column(ForeignKey("episode_summaries.id"))
    status: Mapped[str] = mapped_column(String(30))
    candidate_status: Mapped[str] = mapped_column(String(30))
    score: Mapped[float | None] = mapped_column(Float)
    features: Mapped[dict[str, Any]] = mapped_column(JSON)
    quality_flags: Mapped[list[str]] = mapped_column(JSON)
    input_references: Mapped[dict[str, Any]] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(String(4000))
    recommendation: Mapped[str] = mapped_column(String(2000))
    uncertainty: Mapped[str] = mapped_column(String(2000))
    human_review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_status: Mapped[str] = mapped_column(String(30), default="disabled")
    ai_job_status: Mapped[str] = mapped_column(String(30), default="not_requested")
    provider: Mapped[str | None] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(100))
    rules_version: Mapped[str] = mapped_column(String(60))
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    prompt_version: Mapped[str] = mapped_column(String(60), default="explanation-v1")
    workflow_version: Mapped[str] = mapped_column(String(60), default="fixed-graph-v1")
    retrieved_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    cited_evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_explanation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EvidenceChunk(Base):
    __tablename__ = "evidence_chunks"
    __table_args__ = (
        UniqueConstraint("source_type", "source_reference"),
        Index("ix_evidence_batch_commodity_time", "batch_id", "commodity", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_type: Mapped[str] = mapped_column(String(30))
    source_reference: Mapped[str] = mapped_column(String(100))
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"))
    commodity: Mapped[str] = mapped_column(String(80))
    text: Mapped[str] = mapped_column(String(8000))
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[Any | None] = mapped_column(
        Vector(768).with_variant(JSON(none_as_null=True), "sqlite")
    )
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExplanationJob(Base):
    __tablename__ = "explanation_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('pending','running','done','failed')", name="status"),
        Index("ix_jobs_status_created", "status", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("risk_assessments.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index(
            "uq_alert_unresolved",
            "batch_id",
            "trigger_key",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
            sqlite_where=text("resolved_at IS NULL"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("risk_assessments.id"))
    severity: Mapped[str] = mapped_column(String(20))
    trigger_key: Mapped[str] = mapped_column(String(80))
    message: Mapped[str] = mapped_column(String(2000))
    delivery_status: Mapped[str] = mapped_column(String(30), default="not_attempted")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationAttempt(Base):
    __tablename__ = "notification_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"), index=True)
    provider: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30))
    provider_reference: Mapped[str | None] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
