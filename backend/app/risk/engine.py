import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, pstdev
from typing import Any

from app.core.time import as_utc
from app.risk.policy import RiskPolicy


@dataclass(frozen=True)
class Sample:
    id: str
    device_id: str
    timestamp: datetime
    temperature_c: float
    humidity_pct: float
    gas_adc: int
    warming_up: bool
    simulated: bool


@dataclass(frozen=True)
class Baseline:
    id: str
    device_id: str
    recorded_at: datetime
    gas_adc: int


@dataclass(frozen=True)
class RiskResult:
    candidate_status: str
    score: float | None
    features: dict[str, Any]
    quality_flags: list[str]
    reading_ids: list[str]
    baseline_ids: list[str]
    signature: str
    explanation: str
    recommendation: str
    uncertainty: str


def statistics(values: list[float], timestamps: list[datetime]) -> dict[str, float]:
    origin = timestamps[0]
    hours = [(as_utc(t) - as_utc(origin)).total_seconds() / 3600 for t in timestamps]
    center = mean(hours)
    denominator = sum((t - center) ** 2 for t in hours)
    slope = sum((t - center) * (v - mean(values)) for t, v in zip(hours, values, strict=True))
    return {
        "mean": round(mean(values), 4),
        "min": min(values),
        "max": max(values),
        "stddev": round(pstdev(values), 4),
        "delta": round(values[-1] - values[0], 4),
        "slope_per_hour": round(slope / denominator if denominator else 0, 4),
    }


def evaluate(
    samples: list[Sample],
    baselines: list[Baseline],
    *,
    now: datetime,
    commodity: str,
    expected_devices: list[str],
    policy: RiskPolicy,
) -> RiskResult:
    now = as_utc(now)
    start = now - timedelta(seconds=policy.window_seconds)
    window = sorted(
        (s for s in samples if start <= as_utc(s.timestamp) <= now),
        key=lambda s: (as_utc(s.timestamp), s.id),
    )
    flags: set[str] = set()
    if commodity != policy.commodity:
        flags.add("unsupported_commodity")
    if not expected_devices:
        flags.add("no_active_devices")
    if not window:
        flags.add("missing_readings")
    if any(s.warming_up for s in window):
        flags.add("warming_up_excluded")
    if len({s.simulated for s in window}) > 1:
        flags.add("mixed_real_and_simulated")
    valid = []
    for s in window:
        if s.warming_up:
            continue
        if (
            not all(math.isfinite(v) for v in [s.temperature_c, s.humidity_pct, s.gas_adc])
            or not -40 <= s.temperature_c <= 80
            or not 0 <= s.humidity_pct <= 100
            or not 0 < s.gas_adc < 4095
        ):
            flags.add("implausible_or_saturated_readings")
            continue
        valid.append(s)
    by_device: dict[str, list[Sample]] = defaultdict(list)
    for s in valid:
        by_device[s.device_id].append(s)
    references: dict[str, list[Baseline]] = defaultdict(list)
    for b in sorted(baselines, key=lambda b: (as_utc(b.recorded_at), b.id)):
        references[b.device_id].append(b)
    features: dict[str, Any] = {
        "window_start": start.isoformat(),
        "window_end": now.isoformat(),
        "window_seconds": policy.window_seconds,
        "sample_count": len(window),
        "valid_sample_count": len(valid),
        "simulated": any(s.simulated for s in window),
        "devices": {},
    }
    baseline_ids: set[str] = set()
    device_scores = []
    for device_id in expected_devices:
        rows = by_device.get(device_id, [])
        if len(rows) < policy.min_samples:
            flags.add("insufficient_samples")
        if not rows:
            flags.add("device_missing_readings")
            continue
        times = [as_utc(s.timestamp) for s in rows]
        occupied = {(t - start).total_seconds() // policy.sampling_seconds for t in times}
        coverage = min(1, len(occupied) / (policy.window_seconds / policy.sampling_seconds))
        if coverage < policy.min_coverage:
            flags.add("insufficient_coverage")
        if times[0] > start + timedelta(seconds=policy.sampling_seconds):
            flags.add("window_not_filled")
        if (now - times[-1]).total_seconds() > policy.stale_seconds:
            flags.add("stale_readings")
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)]
        if gaps and max(gaps) > policy.sampling_seconds * policy.max_gap_intervals:
            flags.add("missing_intervals")
        relative = []
        for s in rows:
            candidates = [
                b for b in references[device_id] if as_utc(b.recorded_at) <= as_utc(s.timestamp)
            ]
            if not candidates or candidates[-1].gas_adc <= 0:
                flags.add("missing_baseline")
                continue
            baseline = candidates[-1]
            baseline_ids.add(baseline.id)
            relative.append(s.gas_adc / baseline.gas_adc - 1)
        temperature = statistics([s.temperature_c for s in rows], times)
        humidity = statistics([s.humidity_pct for s in rows], times)
        gas = statistics(relative, times) if len(relative) == len(rows) else None
        details = {
            "temperature_c": temperature,
            "humidity_pct": humidity,
            "relative_uncalibrated_gas_response": gas,
            "coverage": round(coverage, 4),
            "latest_source_timestamp": times[-1].isoformat(),
            "valid_samples": len(rows),
        }
        features["devices"][device_id] = details
        if gas:
            temp_fraction = mean(
                [
                    float(
                        not policy.temperature_low_c <= s.temperature_c <= policy.temperature_high_c
                    )
                    for s in rows
                ]
            )
            humidity_fraction = mean(
                [
                    float(not policy.humidity_low_pct <= s.humidity_pct <= policy.humidity_high_pct)
                    for s in rows
                ]
            )
            factors = {
                "temperature_exposure": temp_fraction * policy.temperature_weight,
                "humidity_exposure": humidity_fraction * policy.humidity_weight,
                "relative_gas_level": min(1, max(0, gas["mean"]) / policy.gas_relative_scale)
                * policy.gas_level_weight,
                "relative_gas_trend": min(
                    1, max(0, gas["slope_per_hour"]) / policy.gas_rise_per_hour_scale
                )
                * policy.gas_trend_weight,
            }
            details["score_factors"] = {k: round(v, 3) for k, v in factors.items()}
            device_scores.append(sum(factors.values()))
    # Baseline changes inside a window can manufacture a trend: require a stable reference.
    if len(baseline_ids) > len(expected_devices):
        flags.add("baseline_changed_in_window")
    features["latest_source_timestamp"] = (
        max(as_utc(s.timestamp) for s in window).isoformat() if window else None
    )
    signature = hashlib.sha256(
        json.dumps(
            {
                "readings": sorted(s.id for s in window),
                "baselines": sorted(baseline_ids),
                "policy": policy.model_dump(),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    fatal = flags - {"warming_up_excluded"}
    score = round(max(device_scores), 2) if device_scores and not fatal else None
    status = "insufficient_data"
    if score is not None:
        status = (
            "spoiling"
            if score >= policy.high_threshold
            else "early_decay"
            if score >= policy.early_threshold
            else "fresh"
        )
    features["score_aggregation"] = "maximum_device_score"
    explanation = (
        f"Insufficient evidence: {', '.join(sorted(fatal))}."
        if fatal
        else f"Operational risk score {score}/100 under illustrative policy {policy.version}."
    )
    recommendation = (
        "Inspect sensor connectivity, warm-up, baseline and window coverage."
        if score is None
        else "Review conditions and inspect the batch before any action."
    )
    uncertainty = (
        "Uncalibrated MQ-135 responses may reflect ripening, temperature or humidity. "
        "Risk labels are not food-safety certification or shelf-life estimates."
    )
    return RiskResult(
        status,
        score,
        features,
        sorted(flags),
        [s.id for s in window],
        sorted(baseline_ids),
        signature,
        explanation,
        recommendation,
        uncertainty,
    )


def transition(
    current: str,
    candidate: str,
    score: float | None,
    *,
    pending: str | None,
    count: int,
    last_signature: str | None,
    signature: str,
    policy: RiskPolicy,
) -> tuple[str, str | None, int]:
    levels = {"fresh": 0, "early_decay": 1, "spoiling": 2}
    if current not in levels or candidate not in levels or levels[candidate] >= levels[current]:
        return candidate, None, 0
    boundary = policy.high_threshold if current == "spoiling" else policy.early_threshold
    if score is None or score > boundary - policy.hysteresis_margin:
        return current, None, 0
    if signature == last_signature:
        return current, pending, count
    count = count + 1 if candidate == pending else 1
    if count >= policy.recovery_confirmations:
        return candidate, None, 0
    return current, candidate, count
