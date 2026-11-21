from typing import Literal

from app.schemas.common import OutputSchema
from app.schemas.operations import AssessmentOut
from app.schemas.resources import BatchOut


class DemoBatchOut(OutputSchema):
    batch: BatchOut
    assessment: AssessmentOut
    reading_count: int
    simulated: Literal[True] = True
