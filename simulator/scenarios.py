import random
from datetime import datetime, timedelta
from typing import Any

SCENARIOS = (
    "stable",
    "deterioration",
    "temperature_excursion",
    "stale",
    "missing",
    "noise",
    "disconnect",
)


def generate(
    *,
    scenario: str,
    seed: int,
    start: datetime,
    count: int,
    interval_seconds: int,
    device_id: str,
    batch_id: str,
    run_id: str,
    warmup_samples: int = 0,
) -> list[dict[str, Any]]:
    if scenario not in SCENARIOS:
        raise ValueError("Unknown scenario")
    if start.tzinfo is None:
        raise ValueError("Start timestamp must include a timezone")
    if count < 1 or interval_seconds < 1:
        raise ValueError("Count and interval must be positive")
    if scenario == "disconnect":
        return []
    rng = random.Random(seed)
    readings = []
    for index in range(count):
        if scenario == "missing" and index % 3 == 0:
            continue
        progress = index / max(1, count - 1)
        temp, humidity, gas = 20.0, 75.0, 1000
        if scenario == "deterioration":
            temp, humidity, gas = 30.0, 97.0, round(1000 + progress * 1000)
        elif scenario == "temperature_excursion" and progress >= 0.5:
            temp = 32.0
        elif scenario == "noise":
            temp += rng.uniform(-4, 4)
            humidity += rng.uniform(-10, 10)
            gas += rng.randint(-150, 150)
        else:
            temp += rng.uniform(-0.25, 0.25)
            humidity += rng.uniform(-1, 1)
            gas += rng.randint(-5, 5)
        timestamp = start + timedelta(seconds=index * interval_seconds)
        if scenario == "stale":
            timestamp -= timedelta(hours=1)
        readings.append(
            {
                "device_id": device_id,
                "batch_id": batch_id,
                "event_id": f"{run_id}:{index}",
                "source_timestamp": timestamp.isoformat(),
                "temperature_c": round(temp, 3),
                "humidity_pct": round(humidity, 3),
                "gas_adc": gas,
                "gas_voltage_v": round(gas / 4095 * 3.3, 4),
                "warming_up": index < warmup_samples,
                "simulated": True,
                "firmware_version": "http-simulator-v1",
            }
        )
    return readings
