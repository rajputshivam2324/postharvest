from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiskPolicy(BaseModel):
    """Illustrative tomato monitoring rules, configurable and not scientifically calibrated."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    version: str = "tomato-demo-v1"
    commodity: str = "tomato"
    window_seconds: int = Field(default=21600, ge=300, le=86400)
    sampling_seconds: int = Field(default=300, ge=30, le=3600)
    min_samples: int = Field(default=12, ge=3, le=10000)
    min_coverage: float = Field(default=0.8, ge=0.5, le=1)
    max_gap_intervals: float = Field(default=3, ge=1, le=10)
    stale_seconds: int = Field(default=900, ge=30, le=3600)
    temperature_low_c: float = 10
    temperature_high_c: float = 25
    humidity_low_pct: float = 60
    humidity_high_pct: float = 95
    gas_relative_scale: float = Field(default=0.5, gt=0)
    gas_rise_per_hour_scale: float = Field(default=0.1, gt=0)
    temperature_weight: float = Field(default=30, ge=0)
    humidity_weight: float = Field(default=10, ge=0)
    gas_level_weight: float = Field(default=40, ge=0)
    gas_trend_weight: float = Field(default=20, ge=0)
    early_threshold: float = Field(default=35, gt=0, lt=100)
    high_threshold: float = Field(default=70, gt=0, le=100)
    hysteresis_margin: float = Field(default=10, ge=0)
    recovery_confirmations: int = Field(default=2, ge=1, le=10)

    @model_validator(mode="after")
    def coherent(self) -> "RiskPolicy":
        if self.sampling_seconds >= self.window_seconds:
            raise ValueError("Sampling interval must be shorter than window")
        if self.min_samples > self.window_seconds // self.sampling_seconds + 1:
            raise ValueError("Minimum samples cannot exceed expected window samples")
        if not self.temperature_low_c < self.temperature_high_c:
            raise ValueError("Temperature bounds must be ordered")
        if not 0 <= self.humidity_low_pct < self.humidity_high_pct <= 100:
            raise ValueError("Humidity bounds must be ordered")
        if not self.hysteresis_margin < self.early_threshold < self.high_threshold:
            raise ValueError("Thresholds and hysteresis must be ordered")
        if (
            abs(
                sum(
                    [
                        self.temperature_weight,
                        self.humidity_weight,
                        self.gas_level_weight,
                        self.gas_trend_weight,
                    ]
                )
                - 100
            )
            > 0.001
        ):
            raise ValueError("Risk weights must sum to 100")
        return self
