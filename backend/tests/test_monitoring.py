from datetime import timedelta

import pytest
from sqlalchemy import event

from app.core.time import utcnow
from app.db.models import SensorReading


def reading_payload(batch, device):
    return {
        "device_id": device["id"],
        "batch_id": batch["id"],
        "event_id": "boot-1:1",
        "temperature_c": 20,
        "humidity_pct": 70,
        "gas_adc": 1000,
        "gas_voltage_v": 0.8,
        "source_timestamp": utcnow().isoformat(),
        "simulated": True,
    }


def test_ingestion_idempotency_and_history(client, monitoring):
    batch, device, auth = monitoring
    payload = reading_payload(batch, device)
    headers = {"X-Device-Token": device["credential"]}
    first = client.post("/api/v1/readings", json=payload, headers=headers)
    assert first.status_code == 201, first.text
    retry = client.post("/api/v1/readings", json=payload, headers=headers)
    assert retry.status_code == 200
    assert retry.json()["reading"]["id"] == first.json()["reading"]["id"]
    assert retry.json()["duplicate"] is True
    payload["gas_adc"] = 1050
    assert client.post("/api/v1/readings", json=payload, headers=headers).status_code == 409
    history = client.get(f"/api/v1/batches/{batch['id']}/readings?limit=1", headers=auth)
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["simulated"] is True
    assert (
        client.get(f"/api/v1/devices/{device['id']}", headers=auth).json()["connection_status"]
        == "online"
    )


def test_latest_reading_is_scoped_and_skips_history_count(client, app, monitoring, headers):
    batch, device, auth = monitoring
    path = f"/api/v1/batches/{batch['id']}/readings/latest"
    empty = client.get(path, headers=auth)
    assert empty.status_code == 200
    assert empty.json() is None

    # Insertion order differs from source time; ties match the history's ID order.
    now = utcnow()
    with app.state.session_factory.begin() as db:
        for reading_id, timestamp in [
            ("latest-a", now),
            ("latest-z", now),
            ("older", now - timedelta(hours=1)),
        ]:
            db.add(
                SensorReading(
                    id=reading_id,
                    batch_id=batch["id"],
                    device_id=device["id"],
                    temperature_c=20,
                    humidity_pct=70,
                    gas_adc=1000,
                    gas_voltage_v=0.8,
                    simulated=True,
                    source_timestamp=timestamp,
                )
            )

    statements = []

    def record_query(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(app.state.engine, "before_cursor_execute", record_query)
    try:
        latest = client.get(path, headers=auth)
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record_query)
    assert latest.status_code == 200
    assert latest.json()["id"] == "latest-z"
    assert len(statements) == 3  # Current user, batch authorization, indexed latest reading.
    assert all("count(" not in statement.lower() for statement in statements)
    assert client.get(path, headers=headers("vendor")).status_code == 404
    assert client.get(path).status_code == 401
    assert client.get("/api/v1/batches/missing/readings/latest", headers=auth).status_code == 404


def test_device_and_user_credentials_are_separate(client, monitoring):
    batch, device, auth = monitoring
    payload = reading_payload(batch, device)
    assert client.post("/api/v1/readings", json=payload, headers=auth).status_code == 401
    device_auth = {"X-Device-Token": device["credential"]}
    assert client.get("/api/v1/batches", headers=device_auth).status_code == 401
    # The server decides the batch from the device's assignment. A stale batch_id from
    # older firmware is reported but never trusted, and never causes the reading to be lost.
    payload["batch_id"] = "another-batch"
    stale = client.post("/api/v1/readings", json=payload, headers=device_auth)
    assert stale.status_code == 201, stale.text
    assert stale.json()["reading"]["batch_id"] == batch["id"]
    assert "ignored" in stale.json()["notice"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("humidity_pct", 101),
        ("gas_adc", -1),
        ("gas_voltage_v", 5),
        ("temperature_c", 90),
        ("source_timestamp", "2026-01-01T12:00:00"),
    ],
)
def test_invalid_readings(client, monitoring, key, value):
    batch, device, _ = monitoring
    payload = reading_payload(batch, device)
    payload[key] = value
    assert (
        client.post(
            "/api/v1/readings", json=payload, headers={"X-Device-Token": device["credential"]}
        ).status_code
        == 422
    )


def test_archive_credential_rotation_and_time_validation(client, monitoring):
    batch, device, auth = monitoring
    payload = reading_payload(batch, device)
    device_auth = {"X-Device-Token": device["credential"]}
    payload["source_timestamp"] = (utcnow() + timedelta(hours=1)).isoformat()
    assert client.post("/api/v1/readings", json=payload, headers=device_auth).status_code == 422
    payload["source_timestamp"] = utcnow().isoformat()
    rotated = client.post(f"/api/v1/devices/{device['id']}/rotate-credential", headers=auth).json()
    assert client.post("/api/v1/readings", json=payload, headers=device_auth).status_code == 401
    device_auth = {"X-Device-Token": rotated["credential"]}
    assert client.post(f"/api/v1/batches/{batch['id']}/archive", headers=auth).status_code == 200
    # Archiving frees the device. Its later readings are held, never added to the archived
    # batch (which is read-only) and never rejected (the firmware would discard them).
    held = client.post("/api/v1/readings", json=payload, headers=device_auth)
    assert held.status_code == 201, held.text
    assert held.json()["reading"]["batch_id"] is None
    assert "not assigned" in held.json()["notice"]
    history = client.get(f"/api/v1/batches/{batch['id']}/readings", headers=auth)
    assert history.json()["total"] == 0


def test_vendor_scope_and_role_enforcement(client, monitoring, headers):
    batch, _, auth = monitoring
    vendor = headers("vendor")
    assert client.get("/api/v1/batches", headers=vendor).json()["total"] == 0
    assert client.get(f"/api/v1/batches/{batch['id']}", headers=vendor).status_code == 404
    assert (
        client.patch(
            f"/api/v1/batches/{batch['id']}", headers=vendor, json={"quantity": 8}
        ).status_code
        == 403
    )
    payload = {
        "identifier": "vendor-batch",
        "commodity": "tomato",
        "quantity": 2,
        "unit": "kg",
        "storage_location": "B",
        "owner_id": "vendor",
    }
    assert client.post("/api/v1/batches", headers=auth, json=payload).status_code == 201
    assert client.get("/api/v1/batches", headers=vendor).json()["total"] == 1


def test_observations_append_only_baselines_and_corrections(client, monitoring):
    batch, device, auth = monitoring
    baseline = client.post(
        f"/api/v1/devices/{device['id']}/baseline",
        headers=auth,
        json={"gas_adc": 1000, "recorded_at": utcnow().isoformat()},
    )
    assert baseline.status_code == 201
    path = f"/api/v1/batches/{batch['id']}/observations"
    payload = {
        "observed_at": utcnow().isoformat(),
        "condition": "Firm tomatoes",
        "visible_mould": False,
    }
    first = client.post(path, json=payload, headers=auth)
    assert first.status_code == 201
    correction = {
        **payload,
        "observation_type": "correction",
        "corrects_id": first.json()["id"],
        "condition": "Correction: slightly soft",
    }
    assert client.post(path, json=correction, headers=auth).status_code == 201
    assert client.get(path, headers=auth).json()["total"] == 2
    assert (
        client.patch(path + "/" + first.json()["id"], json=payload, headers=auth).status_code == 404
    )
    assert (
        client.post(path, json={**correction, "corrects_id": "missing"}, headers=auth).status_code
        == 422
    )
