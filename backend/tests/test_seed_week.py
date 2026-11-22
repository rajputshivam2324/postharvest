from datetime import timedelta

from sqlalchemy import func, select

from app.core.config import Settings
from app.core.time import utcnow
from app.db.models import Alert, Batch, Observation, RiskAssessment, SensorReading, User
from scripts.seed_week import seed_week


def test_seed_week_builds_a_flagged_history_through_the_real_rules(app):
    settings = Settings(
        environment="test", database_url="sqlite://", jwt_secret="t" * 48, _env_file=None
    )
    with app.state.session_factory() as db:
        actor = db.scalar(select(User).where(User.user_id == "operator"))
        result = seed_week(db, actor, settings, progress=lambda *_: None)
        batch = db.get(Batch, result["batch_id"])
        total = db.scalar(
            select(func.count())
            .select_from(SensorReading)
            .where(SensorReading.batch_id == batch.id)
        )
        flagged = db.scalar(
            select(func.count())
            .select_from(SensorReading)
            .where(SensorReading.batch_id == batch.id, SensorReading.simulated.is_(True))
        )
        assessments = list(
            db.scalars(
                select(RiskAssessment)
                .where(RiskAssessment.batch_id == batch.id)
                .order_by(RiskAssessment.created_at)
            )
        )
        alerts = list(db.scalars(select(Alert).where(Alert.batch_id == batch.id)))
        observations = db.scalar(
            select(func.count()).select_from(Observation).where(Observation.batch_id == batch.id)
        )
        # About seven days of five-minute samples, minus the 40-minute Wi-Fi gap.
        assert 1950 < total < 2016
        assert flagged == total, "every back-filled reading stays flagged as simulated"
        assert batch.attributes["simulated"] is True
        assert observations == 7
        assert len(assessments) > 70
        # The history is stamped with the times it describes, spread over the week.
        span = assessments[-1].created_at - assessments[0].created_at
        assert span.total_seconds() > 6 * 24 * 3600
        assert assessments[-1].created_at.replace(tzinfo=None) <= utcnow().replace(tzinfo=None)
        statuses = [a.status for a in assessments]
        for expected in ("fresh", "insufficient_data", "early_decay"):
            assert expected in statuses
        assert statuses[-1] == "fresh", "the batch has recovered by now"
        assert {a.trigger_key for a in alerts} >= {"early_decay", "insufficient_data"}
        assert all(a.resolved_at is not None for a in alerts), "no alert is left open"
        assert all(a.acknowledged_at is not None for a in alerts)


def test_seed_week_refuses_to_run_twice(app):
    import pytest

    settings = Settings(
        environment="test", database_url="sqlite://", jwt_secret="t" * 48, _env_file=None
    )
    with app.state.session_factory() as db:
        actor = db.scalar(select(User).where(User.user_id == "operator"))
        seed_week(db, actor, settings, days=5, progress=lambda *_: None)
        with pytest.raises(SystemExit):
            seed_week(db, actor, settings, days=5, progress=lambda *_: None)


def test_seed_week_never_touches_other_batches_alerts(app):
    """Regression: acknowledging alerts must stay inside the seeded batch."""
    from app.db.models import Alert, DecisionLog
    from app.schemas.resources import BatchCreate
    from app.services.assessments import assess
    from app.services.resources import create_batch

    settings = Settings(
        environment="test", database_url="sqlite://", jwt_secret="t" * 48, _env_file=None
    )
    with app.state.session_factory() as db:
        actor = db.scalar(select(User).where(User.user_id == "operator"))
        other = create_batch(
            db,
            BatchCreate(
                identifier="OLD-BATCH",
                commodity="tomato",
                quantity=1,
                unit="box",
                storage_location="Bench",
            ),
            actor,
        )
        assess(db, other.id, actor, settings)  # no readings: raises an insufficient-data alert
        old = db.scalar(select(Alert).where(Alert.batch_id == other.id))
        assert old is not None and old.acknowledged_at is None
        # Like the real October alerts: old enough that the seed's clock passes their delay.
        old.created_at = utcnow() - timedelta(days=30)
        db.commit()
        before = db.scalar(
            select(func.count()).select_from(DecisionLog).where(DecisionLog.batch_id == other.id)
        )
        seed_week(db, actor, settings, days=7, progress=lambda *_: None)
        db.refresh(old)
        after = db.scalar(
            select(func.count()).select_from(DecisionLog).where(DecisionLog.batch_id == other.id)
        )
        assert old.acknowledged_at is None and old.acknowledged_by is None
        assert before == after


def test_chat_evidence_includes_the_week_so_history_questions_can_be_answered(app):
    from app.core.time import utcnow
    from app.services.chat import _week_item

    settings = Settings(
        environment="test", database_url="sqlite://", jwt_secret="t" * 48, _env_file=None
    )
    with app.state.session_factory() as db:
        actor = db.scalar(select(User).where(User.user_id == "operator"))
        result = seed_week(db, actor, settings, progress=lambda *_: None)
        item = _week_item(db, db.get(Batch, result["batch_id"]), utcnow())
        assert item is not None and item.kind == "history"
        for expected in ("elevated risk", "insufficient evidence", "low risk"):
            assert expected in item.text
        assert "cleared" in item.text and "Readings in the period" in item.text
        # Internal status codes never reach the model.
        assert "early_decay" not in item.text
        assert "spoiling" not in item.text


def test_live_feed_sends_the_next_reading_through_real_ingestion(app):
    from datetime import timedelta

    from app.core.time import set_clock
    from app.db.models import Device
    from scripts.live_feed import feed_once

    settings = Settings(
        environment="test", database_url="sqlite://", jwt_secret="t" * 48, _env_file=None
    )
    with app.state.session_factory() as db:
        actor = db.scalar(select(User).where(User.user_id == "operator"))
        result = seed_week(db, actor, settings, progress=lambda *_: None)
        before = db.scalar(
            select(func.count())
            .select_from(SensorReading)
            .where(SensorReading.batch_id == result["batch_id"])
        )
        try:
            set_clock(utcnow() + timedelta(minutes=6))  # the next five-minute tick
            token, duplicate = feed_once(db, settings, "ESP32-24A1604F7B2C", actor)
            again = feed_once(db, settings, "ESP32-24A1604F7B2C", actor, token)
        finally:
            set_clock(None)
        after = db.scalar(
            select(func.count())
            .select_from(SensorReading)
            .where(SensorReading.batch_id == result["batch_id"])
        )
        newest = db.scalar(
            select(SensorReading)
            .where(SensorReading.batch_id == result["batch_id"])
            .order_by(SensorReading.source_timestamp.desc())
        )
        assert duplicate is False and again[1] is True, "a repeated tick is not stored twice"
        assert after == before + 1
        assert newest.simulated is True
        assert db.scalar(select(Device).where(Device.identifier == "ESP32-24A1604F7B2C")).batch_id


def test_seeded_climate_matches_faridabad_in_november(app):
    """Nights near 10 C, dry warm afternoons, humid mornings: not a cold room."""
    from collections import defaultdict

    from scripts.climate import IST

    settings = Settings(
        environment="test", database_url="sqlite://", jwt_secret="t" * 48, _env_file=None
    )
    with app.state.session_factory() as db:
        actor = db.scalar(select(User).where(User.user_id == "operator"))
        result = seed_week(db, actor, settings, progress=lambda *_: None)
        rows = list(
            db.scalars(select(SensorReading).where(SensorReading.batch_id == result["batch_id"]))
        )
    by_day = defaultdict(list)
    for r in rows:
        local = r.source_timestamp.replace(tzinfo=None) + IST
        by_day[local.date()].append((local.hour + local.minute / 60, r))
    full_days = [v for v in by_day.values() if len(v) > 250]
    assert len(full_days) >= 5
    for day in full_days:
        lows = min(r.temperature_c for _, r in day)
        highs = max(r.temperature_c for _, r in day)
        assert 8.5 <= lows <= 14.5, "nights are cool, not a 14 C cold room"
        assert 23 <= highs <= 34
        # the coldest reading is around dawn, the warmest in the afternoon
        assert min(day, key=lambda x: x[1].temperature_c)[0] < 9
        assert 12 <= max(day, key=lambda x: x[1].temperature_c)[0] <= 17
    assert min(r.temperature_c for r in rows) <= 11, "at least one night near 10 C"
    nights = [r.humidity_pct for _, r in sum(full_days, []) if _ < 7]
    afternoons = [r.humidity_pct for _, r in sum(full_days, []) if 13 <= _ <= 16]
    assert sum(nights) / len(nights) > sum(afternoons) / len(afternoons) + 25
    assert all(0 < r.humidity_pct < 100 for r in rows)
    # Room-air gas level in line with this ESP32's real readings (about 600 to 660).
    assert 560 <= sorted(r.gas_adc for r in rows)[len(rows) // 2] <= 680
