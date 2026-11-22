"""A plausible outdoor climate for Faridabad (Sector 7, Haryana, India, about 28.4 N 77.3 E).

Used only to make simulated sensor history look like the place it is meant to describe.
The monthly anchors are approximate climate normals for the Delhi NCR plains, written from
general knowledge and checked against the real ESP32 in the same room (25.7 C and 53 % RH
around noon on 22 November). They are not measurements and not a weather record: day-to-day
variation comes from a seeded random generator.
"""

import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta

IST = timedelta(hours=5, minutes=30)

# (month, day): (daily maximum C, daily minimum C, dew point C). Linear between anchors,
# wrapping around the new year.
ANCHORS: list[tuple[tuple[int, int], tuple[float, float, float]]] = [
    ((1, 1), (19.0, 6.0, 6.0)),
    ((2, 1), (21.0, 8.0, 7.0)),
    ((3, 1), (27.0, 12.0, 8.0)),
    ((4, 1), (34.0, 18.0, 9.0)),
    ((5, 1), (39.0, 24.0, 10.0)),
    ((6, 1), (40.0, 28.0, 14.0)),
    ((7, 1), (36.0, 28.0, 23.0)),
    ((8, 1), (34.0, 27.0, 24.0)),
    ((9, 1), (34.0, 25.0, 22.0)),
    ((10, 1), (34.0, 22.0, 18.0)),
    ((10, 15), (32.0, 20.0, 15.0)),
    ((11, 1), (30.0, 16.5, 13.5)),
    ((11, 15), (27.0, 11.5, 11.5)),
    ((12, 1), (23.5, 8.0, 8.5)),
    ((12, 15), (21.0, 6.5, 7.0)),
]
MIN_HOUR, MAX_HOUR = 6.5, 14.5  # local clock times of the daily minimum and maximum


@dataclass(frozen=True)
class Day:
    tmax: float
    tmin: float
    dew: float


def _normal(day: date) -> Day:
    year = day.year
    points = [(date(year, m, d), v) for (m, d), v in ANCHORS]
    points.append((date(year + 1, 1, 1), ANCHORS[0][1]))
    points.insert(0, (date(year - 1, 12, 15), ANCHORS[-1][1]))
    for (d0, v0), (d1, v1) in zip(points, points[1:], strict=False):
        if d0 <= day <= d1:
            f = (day - d0).days / max(1, (d1 - d0).days)
            return Day(*(a + (b - a) * f for a, b in zip(v0, v1, strict=True)))
    return Day(*ANCHORS[0][1])


def _gauss(seed: int, day: date, name: str) -> float:
    return random.Random(f"{seed}:{name}:{day.toordinal()}").gauss(0, 1)


def day_weather(day: date, seed: int) -> Day:
    """The normal for the date plus a smoothed, seeded weather anomaly (cloudy days are
    cooler by day, warmer at night and more humid)."""
    base = _normal(day)

    def smooth(name: str) -> float:
        return (
            0.5 * _gauss(seed, day, name)
            + 0.25 * _gauss(seed, day - timedelta(days=1), name)
            + 0.25 * _gauss(seed, day + timedelta(days=1), name)
        )  # about 0.6 standard deviations

    cloud = min(1.2, max(0.0, smooth("cloud")))
    return Day(
        tmax=base.tmax + 1.8 * smooth("max") - 1.4 * cloud,
        tmin=base.tmin + 1.5 * smooth("min") + 0.7 * cloud,
        dew=base.dew + 2.0 * smooth("dew") + 0.8 * cloud,
    )


def _cos_blend(a: float, b: float, x: float, bias: float = 1.0) -> float:
    """Smooth a to b. bias < 1 front-loads the change (warming is fastest in the morning)."""
    x = min(1.0, max(0.0, x)) ** bias
    return a + (b - a) * (1 - math.cos(math.pi * x)) / 2


def outdoor(local: datetime, seed: int) -> tuple[float, float]:
    """(air temperature C, dew point C) outdoors at a local (IST) wall-clock time."""
    h = local.hour + local.minute / 60 + local.second / 3600
    today = local.date()
    cur = day_weather(today, seed)
    if h < MIN_HOUR:  # cooling overnight from yesterday's maximum
        prev = day_weather(today - timedelta(days=1), seed)
        span = 24 - MAX_HOUR + MIN_HOUR
        temperature = _cos_blend(prev.tmax, cur.tmin, (h + 24 - MAX_HOUR) / span)
        dew = prev.dew + (cur.dew - prev.dew) * (h + 24) / 48
    elif h < MAX_HOUR:  # warming through the morning
        temperature = _cos_blend(
            cur.tmin, cur.tmax, (h - MIN_HOUR) / (MAX_HOUR - MIN_HOUR), bias=0.8
        )
        dew = cur.dew
    else:  # cooling from the afternoon maximum into the night
        nxt = day_weather(today + timedelta(days=1), seed)
        span = 24 - MAX_HOUR + MIN_HOUR
        temperature = _cos_blend(cur.tmax, nxt.tmin, (h - MAX_HOUR) / span)
        dew = cur.dew + (nxt.dew - cur.dew) * h / 48
    # Dry afternoon air mixes down: the dew point dips a little between 08:00 and 20:00.
    if 8 <= h <= 20:
        dew -= 1.3 * math.sin(math.pi * (h - 8) / 12)
    return temperature, dew


def relative_humidity(temperature: float, dew: float) -> float:
    """RH in % from air temperature and dew point (Magnus). Air cannot be below its dew
    point, so on cold nights the dew point is capped just under the air temperature (mist)."""
    dew = min(dew, temperature - 0.6)
    a, b = 17.625, 243.04
    return 100 * math.exp(a * dew / (b + dew)) / math.exp(a * temperature / (b + temperature))


def box_conditions(
    when_utc: datetime, seed: int, *, damping: float = 0.97, lag_minutes: int = 30
) -> tuple[float, float]:
    """(C, %RH) for a sensor sitting in a box in an unheated room: slightly damped and
    delayed compared with the open air outside."""
    local = (when_utc + IST).replace(tzinfo=None)
    delayed = local - timedelta(minutes=lag_minutes)
    outside, dew = outdoor(delayed, seed)
    today = day_weather(local.date(), seed)
    mean = (today.tmax + today.tmin) / 2
    temperature = mean + damping * (outside - mean) + 0.3
    return temperature, min(97.5, relative_humidity(temperature, dew) + 3.0)
