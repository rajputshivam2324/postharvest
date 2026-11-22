from datetime import UTC, datetime, timedelta

from app.db.models import Device, SensorReading

START = datetime(2026, 11, 15, 8, 20, tzinfo=UTC)


def fill(app, batch_id, count, device_identifier="esp32-1"):
    """`count` five-minute readings, temperature rising 0.01 C per reading."""
    with app.state.session_factory.begin() as db:
        device = db.query(Device).filter(Device.identifier == device_identifier).one()
        for i in range(count):
            db.add(
                SensorReading(
                    device_id=device.id,
                    batch_id=batch_id,
                    event_id=f"e{i}",
                    temperature_c=10 + i * 0.01,
                    humidity_pct=50,
                    gas_adc=600,
                    gas_voltage_v=0.6,
                    simulated=True,
                    source_timestamp=START + timedelta(minutes=5 * i),
                )
            )


def test_a_long_range_is_covered_from_start_to_end_not_just_its_first_page(client, app, monitoring):
    batch, _, auth = monitoring
    fill(app, batch["id"], 1728)  # six days
    # The table endpoint still pages 200 at a time...
    page = client.get(f"/api/v1/batches/{batch['id']}/readings?limit=200", headers=auth).json()
    assert page["total"] == 1728 and len(page["items"]) == 200
    # ...but the chart series spans the whole range in a bounded number of points.
    series = client.get(
        f"/api/v1/batches/{batch['id']}/readings/series?max_points=300", headers=auth
    ).json()
    assert series["total"] == 1728
    assert series["bucket_seconds"] > 0
    assert 100 < len(series["points"]) <= 320
    times = [datetime.fromisoformat(p["source_timestamp"]) for p in series["points"]]
    assert times == sorted(times)
    span = (times[-1] - times[0]).total_seconds()
    assert span > 5.9 * 86400, "covers the six days, not the first 17 hours"
    # Averaging keeps the shape: the first bucket is low, the last is high.
    assert series["points"][0]["temperature_c"] < 11 < 26 < series["points"][-1]["temperature_c"]
    assert sum(p["samples"] for p in series["points"]) == 1728


def test_a_short_range_returns_every_reading_unaveraged(client, app, monitoring):
    batch, _, auth = monitoring
    fill(app, batch["id"], 40)
    series = client.get(f"/api/v1/batches/{batch['id']}/readings/series", headers=auth).json()
    assert series["bucket_seconds"] == 0 and len(series["points"]) == 40
    assert all(p["samples"] == 1 for p in series["points"])


def test_series_respects_the_chosen_range_and_validates_it(client, app, monitoring):
    batch, _, auth = monitoring
    fill(app, batch["id"], 600)
    lo = (START + timedelta(hours=10)).isoformat().replace("+00:00", "Z")
    hi = (START + timedelta(hours=20)).isoformat().replace("+00:00", "Z")
    series = client.get(
        f"/api/v1/batches/{batch['id']}/readings/series",
        params={"start": lo, "end": hi},
        headers=auth,
    ).json()
    assert series["total"] == 121  # 10 hours of five-minute readings, both ends included
    backwards = client.get(
        f"/api/v1/batches/{batch['id']}/readings/series",
        params={"start": hi, "end": lo},
        headers=auth,
    )
    assert backwards.status_code == 422
    too_few = client.get(
        f"/api/v1/batches/{batch['id']}/readings/series?max_points=10", headers=auth
    )
    assert too_few.status_code == 422


def test_series_is_scoped_to_what_the_user_may_see(client, app, monitoring, headers):
    batch, _, _ = monitoring
    fill(app, batch["id"], 10)
    other = client.get(f"/api/v1/batches/{batch['id']}/readings/series", headers=headers("vendor"))
    assert other.status_code in (403, 404), "a vendor who does not own the batch sees nothing"
