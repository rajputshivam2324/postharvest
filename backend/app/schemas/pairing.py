from datetime import datetime

from pydantic import Field

from app.schemas.common import InputSchema, OutputSchema
from app.schemas.resources import DeviceOut


class PairingOut(OutputSchema):
    device_id: str
    # Shown once. Only a keyed hash is stored, so it cannot be shown again.
    pairing_code: str
    expires_at: datetime


class DevicePairingOut(DeviceOut):
    pairing_code: str
    pairing_expires_at: datetime


class PairingClaim(InputSchema):
    code: str = Field(min_length=1, max_length=32)


class PairingClaimed(OutputSchema):
    device_id: str
    identifier: str
    # The permanent device credential, returned once to the device that holds the code.
    credential: str
    simulated: bool
    sampling_seconds: int
