from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.common import InputSchema, OutputSchema

RiskStatus = Literal["unknown", "fresh", "early_decay", "spoiling", "insufficient_data"]


class BatchCreate(InputSchema):
    identifier: str = Field(min_length=1, max_length=100)
    commodity: str = Field(min_length=1, max_length=80)
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=20)
    storage_location: str = Field(min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    attributes: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict, max_length=30
    )
    owner_id: str | None = Field(default=None, max_length=36)


class BatchUpdate(InputSchema):
    quantity: float | None = Field(default=None, gt=0)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    storage_location: str | None = Field(default=None, min_length=1, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    attributes: dict[str, str | int | float | bool | None] | None = Field(
        default=None, max_length=30
    )
    owner_id: str | None = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def required_fields_not_null(self) -> "BatchUpdate":
        for field in self.model_fields_set - {"notes"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if not self.model_fields_set:
            raise ValueError("At least one field required")
        return self


class BatchOut(OutputSchema):
    id: str
    identifier: str
    owner_id: str
    commodity: str
    quantity: float
    unit: str
    storage_location: str
    notes: str | None
    attributes: dict[str, Any]
    status: RiskStatus
    archived: bool
    created_at: datetime
    updated_at: datetime


class DeviceCreate(InputSchema):
    identifier: str = Field(min_length=1, max_length=100)
    # Optional: a device can be registered first and assigned to a batch later.
    batch_id: str | None = Field(default=None, min_length=1, max_length=36)
    simulated: bool = False
    firmware_version: str | None = Field(default=None, max_length=80)


class DeviceUpdate(InputSchema):
    active: bool


class DeviceOut(OutputSchema):
    id: str
    identifier: str
    batch_id: str | None
    active: bool
    simulated: bool
    last_seen_at: datetime | None
    firmware_version: str | None
    created_at: datetime
    # None until the device has its credential; an unpaired device cannot send readings.
    paired_at: datetime | None
    connection_status: Literal["disabled", "unpaired", "never_seen", "online", "stale"]


class AssignmentCreate(InputSchema):
    batch_id: str = Field(min_length=1, max_length=36)
    # Moving a device that already serves another batch must be explicit.
    replace: bool = False
    note: str | None = Field(default=None, max_length=500)


class AssignmentOut(OutputSchema):
    id: str
    device_id: str
    batch_id: str
    assigned_by: str | None
    assigned_at: datetime
    released_at: datetime | None
    released_by: str | None
    note: str | None


class VendorOut(OutputSchema):
    id: str
    user_id: str


class DeviceRegistered(DeviceOut):
    credential: str


class CredentialOut(InputSchema):
    device_id: str
    credential: str


class BaselineCreate(InputSchema):
    gas_adc: int = Field(gt=0, le=4095)
    recorded_at: AwareDatetime
    notes: str | None = Field(default=None, max_length=2000)


class BaselineOut(OutputSchema):
    id: str
    device_id: str
    actor_id: str
    gas_adc: int
    recorded_at: datetime
    notes: str | None
    created_at: datetime


class ReadingCreate(InputSchema):
    device_id: str = Field(min_length=1, max_length=36)
    # Deprecated: the batch is taken from the device's assignment. Older firmware still
    # sends it, so it is accepted and, when present, must match that assignment.
    batch_id: str | None = Field(default=None, min_length=1, max_length=36)
    event_id: str | None = Field(default=None, min_length=1, max_length=150)
    temperature_c: float = Field(ge=-40, le=80)
    humidity_pct: float = Field(ge=0, le=100)
    gas_adc: int = Field(ge=0, le=4095)
    gas_voltage_v: float = Field(ge=0, le=3.3)
    warming_up: bool = False
    simulated: bool = False
    firmware_version: str | None = Field(default=None, max_length=80)
    source_timestamp: AwareDatetime


class ReadingOut(OutputSchema):
    id: str
    device_id: str
    batch_id: str | None
    event_id: str | None
    temperature_c: float
    humidity_pct: float
    gas_adc: int
    gas_voltage_v: float
    warming_up: bool
    simulated: bool
    firmware_version: str | None
    source_timestamp: datetime
    ingested_at: datetime


class IngestionOut(InputSchema):
    reading: ReadingOut
    duplicate: bool
    # Human-readable hint for firmware logs, for example an unassigned device.
    notice: str | None = None


class ObservationCreate(InputSchema):
    observation_type: Literal["routine", "start_condition", "final_outcome", "correction"] = (
        "routine"
    )
    observed_at: AwareDatetime
    condition: str = Field(min_length=1, max_length=500)
    firmness: str | None = Field(default=None, max_length=100)
    visible_mould: bool | None = None
    weight_kg: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=2000)
    photo_reference: str | None = Field(default=None, max_length=500)
    corrects_id: str | None = Field(default=None, max_length=36)

    @model_validator(mode="after")
    def correction_reference(self) -> "ObservationCreate":
        if (self.observation_type == "correction") != (self.corrects_id is not None):
            raise ValueError("Corrections require a reference; other types cannot correct records")
        return self


class ObservationOut(OutputSchema):
    id: str
    batch_id: str
    observer_id: str
    observation_type: str
    observed_at: datetime
    condition: str
    firmness: str | None
    visible_mould: bool | None
    weight_kg: float | None
    notes: str | None
    photo_reference: str | None
    corrects_id: str | None
    created_at: datetime
