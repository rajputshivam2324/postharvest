from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from simulator.scenarios import generate

from app.risk.engine import Baseline, Sample, evaluate, transition
from app.risk.policy import RiskPolicy

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)
POLICY = RiskPolicy(window_seconds=3600, sampling_seconds=300, min_samples=6)


def scenario_samples(scenario="stable", warmup=0):
    payloads = generate(
        scenario=scenario,
        seed=42,
        start=NOW - timedelta(hours=1),
        count=13,
        interval_seconds=300,
        device_id="device",
        batch_id="batch",
        run_id="run",
        warmup_samples=warmup,
    )
    return [
        Sample(
            p["event_id"],
            p["device_id"],
            datetime.fromisoformat(p["source_timestamp"]),
            p["temperature_c"],
            p["humidity_pct"],
            p["gas_adc"],
            p["warming_up"],
            p["simulated"],
        )
        for p in payloads
    ]


def evaluate_scenario(scenario="stable", samples=None, baselines=None):
    return evaluate(
        samples if samples is not None else scenario_samples(scenario),
        baselines
        if baselines is not None
        else [Baseline("baseline", "device", NOW - timedelta(hours=2), 1000)],
        now=NOW,
        commodity="tomato",
        expected_devices=["device"],
        policy=POLICY,
    )


def test_stable_rising_and_excursion_are_deterministic():
    stable = evaluate_scenario()
    assert stable.candidate_status == "fresh"
    assert stable.score < 5
    rising = evaluate_scenario("deterioration")
    assert rising.candidate_status == "spoiling"
    assert rising.score >= POLICY.high_threshold
    assert rising == evaluate_scenario("deterioration")
    excursion = evaluate_scenario("temperature_excursion")
    assert excursion.score > stable.score
    assert rising.features["simulated"] is True


@pytest.mark.parametrize(
    "scenario,flag",
    [
        ("stale", "stale_readings"),
        ("missing", "insufficient_coverage"),
        ("disconnect", "missing_readings"),
    ],
)
def test_quality_cases(scenario, flag):
    result = evaluate_scenario(scenario)
    assert result.candidate_status == "insufficient_data"
    assert result.score is None
    assert flag in result.quality_flags


def test_warmup_baseline_and_invalid_measurements():
    warm = evaluate_scenario(samples=scenario_samples(warmup=13))
    assert "warming_up_excluded" in warm.quality_flags
    assert warm.score is None
    absent = evaluate_scenario(baselines=[])
    assert "missing_baseline" in absent.quality_flags
    # A baseline recorded after the window cannot be applied retroactively.
    future = evaluate_scenario(
        baselines=[Baseline("future", "device", NOW + timedelta(seconds=1), 1000)]
    )
    assert future.score is None
    rows = scenario_samples()
    for bad in [
        replace(rows[5], temperature_c=float("nan")),
        replace(rows[5], gas_adc=4095),
        replace(rows[5], humidity_pct=120),
    ]:
        result = evaluate_scenario(samples=rows[:5] + [bad] + rows[6:])
        assert "implausible_or_saturated_readings" in result.quality_flags
        assert result.score is None


def test_full_window_multiple_devices_and_mixed_sources():
    partial = evaluate_scenario(samples=scenario_samples()[5:])
    assert "window_not_filled" in partial.quality_flags
    rows = scenario_samples()
    mixed = evaluate_scenario(samples=rows[:-1] + [replace(rows[-1], simulated=False)])
    assert "mixed_real_and_simulated" in mixed.quality_flags
    missing = evaluate(
        rows,
        [Baseline("b", "device", NOW - timedelta(hours=2), 1000)],
        now=NOW,
        commodity="tomato",
        expected_devices=["device", "missing"],
        policy=POLICY,
    )
    assert "device_missing_readings" in missing.quality_flags


def test_baseline_change_quality_and_unsupported_commodity():
    changed = evaluate_scenario(
        baselines=[
            Baseline("b1", "device", NOW - timedelta(hours=2), 1000),
            Baseline("b2", "device", NOW - timedelta(minutes=20), 1400),
        ]
    )
    assert "baseline_changed_in_window" in changed.quality_flags
    unsupported = evaluate(
        scenario_samples(),
        [],
        now=NOW,
        commodity="apple",
        expected_devices=["device"],
        policy=POLICY,
    )
    assert "unsupported_commodity" in unsupported.quality_flags


def test_hysteresis_needs_distinct_new_evidence():
    kwargs = {"policy": POLICY, "last_signature": "older", "signature": "new"}
    first = transition("spoiling", "fresh", 10, pending=None, count=0, **kwargs)
    assert first == ("spoiling", "fresh", 1)
    repeated = transition(
        "spoiling",
        "fresh",
        10,
        pending="fresh",
        count=1,
        last_signature="new",
        signature="new",
        policy=POLICY,
    )
    assert repeated == first
    recovered = transition(
        "spoiling",
        "fresh",
        10,
        pending="fresh",
        count=1,
        last_signature="new",
        signature="newer",
        policy=POLICY,
    )
    assert recovered == ("fresh", None, 0)
    boundary = transition("early_decay", "fresh", 30, pending=None, count=0, **kwargs)
    assert boundary[0] == "early_decay"
    assert (
        transition("spoiling", "insufficient_data", None, pending=None, count=0, **kwargs)[0]
        == "insufficient_data"
    )


def test_simulator_seed_and_event_ids():
    args = dict(
        scenario="noise",
        seed=7,
        start=NOW,
        count=10,
        interval_seconds=300,
        device_id="d",
        batch_id="b",
        run_id="fixed",
    )
    assert generate(**args) == generate(**args)
    assert all(row["simulated"] for row in generate(**args))
    assert len({row["event_id"] for row in generate(**args)}) == 10
