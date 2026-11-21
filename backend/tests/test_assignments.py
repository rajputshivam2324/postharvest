from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.time import utcnow
from app.db.models import DeviceAssignment, SensorReading
from app.repositories.assessments import load_window

# Fixed per test run so a retried reading carries an identical payload, as real firmware does.
NOW = utcnow()
BATCH = {"commodity": "tomato", "quantity": 5, "unit": "kg", "storage_location": "room 1"}


def make_batch(client, auth, identifier, **extra):
    response = client.post(
        "/api/v1/batches", headers=auth, json={**BATCH, "identifier": identifier, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_device(client, auth, identifier="esp32-free", **extra):
    response = client.post(
        "/api/v1/devices",
        headers=auth,
        json={"identifier": identifier, "simulated": True, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def send(client, device, n, **extra):
    """A reading from current firmware: no batch_id."""
    payload = {
        "device_id": device["id"],
        "event_id": f"evt-{n}",
        "temperature_c": 20,
        "humidity_pct": 70,
        "gas_adc": 1000 + n,
        "gas_voltage_v": 0.8,
        "source_timestamp": (NOW - timedelta(minutes=10 - n)).isoformat(),
        "simulated": True,
        **extra,
    }
    return client.post(
        "/api/v1/readings", json=payload, headers={"X-Device-Token": device["credential"]}
    )


def history(client, auth, batch):
    return client.get(f"/api/v1/batches/{batch['id']}/readings", headers=auth).json()


def test_device_registers_unassigned_and_holds_readings(client, headers):
    auth = headers("operator")
    device = make_device(client, auth)
    assert device["batch_id"] is None

    response = send(client, device, 1)
    assert response.status_code == 201, response.text  # not an error: firmware drops 4xx
    assert response.json()["reading"]["batch_id"] is None
    assert "not assigned" in response.json()["notice"]

    latest = client.get(f"/api/v1/devices/{device['id']}/readings/latest", headers=auth).json()
    assert latest["id"] == response.json()["reading"]["id"]
    assert (
        client.get(f"/api/v1/devices/{device['id']}", headers=auth).json()["connection_status"]
        == "online"
    )
    free = client.get("/api/v1/devices?unassigned=true", headers=auth).json()
    assert [d["id"] for d in free["items"]] == [device["id"]]


def test_assign_move_and_release_keep_every_reading_in_its_original_batch(client, headers):
    auth = headers("operator")
    first, second = make_batch(client, auth, "batch-a"), make_batch(client, auth, "batch-b")
    device = make_device(client, auth)
    path = f"/api/v1/devices/{device['id']}/assignment"

    assigned = client.post(path, headers=auth, json={"batch_id": first["id"]})
    assert assigned.status_code == 200, assigned.text
    again = client.post(path, headers=auth, json={"batch_id": first["id"]})
    assert again.json()["id"] == assigned.json()["id"]  # idempotent
    assert send(client, device, 1).json()["reading"]["batch_id"] == first["id"]

    refused = client.post(path, headers=auth, json={"batch_id": second["id"]})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "device_assigned"
    moved = client.post(path, headers=auth, json={"batch_id": second["id"], "replace": True})
    assert moved.status_code == 200, moved.text
    assert send(client, device, 2).json()["reading"]["batch_id"] == second["id"]

    released = client.delete(path, headers=auth)
    assert released.status_code == 200 and released.json()["batch_id"] is None
    assert client.delete(path, headers=auth).status_code == 200  # idempotent
    assert send(client, device, 3).json()["reading"]["batch_id"] is None

    # Nothing moved retroactively: each batch kept exactly the readings it earned.
    assert [r["gas_adc"] for r in history(client, auth, first)["items"]] == [1001]
    assert [r["gas_adc"] for r in history(client, auth, second)["items"]] == [1002]

    trail = client.get(f"/api/v1/devices/{device['id']}/assignments", headers=auth).json()
    assert [a["batch_id"] for a in trail["items"]] == [second["id"], first["id"]]
    assert all(a["released_at"] for a in trail["items"])
    # Both batches still list the device that served them.
    for batch in (first, second):
        listed = client.get(f"/api/v1/devices?batch_id={batch['id']}", headers=auth).json()
        assert [d["id"] for d in listed["items"]] == [device["id"]]


def test_database_allows_one_open_assignment_per_device(client, app, headers):
    auth = headers("operator")
    batch = make_batch(client, auth, "batch-a")
    device = make_device(client, auth, batch_id=batch["id"])
    with app.state.session_factory() as db:
        open_rows = db.scalar(
            select(func.count())
            .select_from(DeviceAssignment)
            .where(
                DeviceAssignment.device_id == device["id"], DeviceAssignment.released_at.is_(None)
            )
        )
    assert open_rows == 1
    assert device["batch_id"] == batch["id"]  # registering with a batch still works


def test_archiving_frees_the_device_and_preserves_the_batch(client, headers):
    auth = headers("operator")
    old, new = make_batch(client, auth, "old"), make_batch(client, auth, "new")
    device = make_device(client, auth, batch_id=old["id"])
    assert send(client, device, 1).status_code == 201
    assert client.post(f"/api/v1/batches/{old['id']}/archive", headers=auth).status_code == 200

    free = client.get(f"/api/v1/devices/{device['id']}", headers=auth).json()
    assert free["batch_id"] is None
    reused = client.post(
        f"/api/v1/devices/{device['id']}/assignment", headers=auth, json={"batch_id": new["id"]}
    )
    assert reused.status_code == 200, reused.text
    assert history(client, auth, old)["total"] == 1
    # An archived batch is read-only, so it can't take a device back.
    again = client.post(
        f"/api/v1/devices/{device['id']}/assignment",
        headers=auth,
        json={"batch_id": old["id"], "replace": True},
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "batch_archived"


def test_assessment_window_keeps_readings_from_devices_that_moved_on(client, app, headers):
    auth = headers("operator")
    first, second = make_batch(client, auth, "batch-a"), make_batch(client, auth, "batch-b")
    device = make_device(client, auth, batch_id=first["id"])
    for n in (1, 2, 3):
        assert send(client, device, n).status_code == 201
    client.post(
        f"/api/v1/devices/{device['id']}/assignment",
        headers=auth,
        json={"batch_id": second["id"], "replace": True},
    )
    now = utcnow()
    with app.state.session_factory() as db:
        samples, _, device_ids = load_window(db, first["id"], now - timedelta(hours=1), now)
        other, _, other_ids = load_window(db, second["id"], now - timedelta(hours=1), now)
    assert len(samples) == 3 and device_ids == [device["id"]]
    assert other == [] and other_ids == [device["id"]]


def test_retry_after_a_move_replays_the_original_reading(client, headers):
    auth = headers("operator")
    first, second = make_batch(client, auth, "batch-a"), make_batch(client, auth, "batch-b")
    device = make_device(client, auth, batch_id=first["id"])
    original = send(client, device, 1)
    client.post(
        f"/api/v1/devices/{device['id']}/assignment",
        headers=auth,
        json={"batch_id": second["id"], "replace": True},
    )
    retry = send(client, device, 1)
    assert retry.status_code == 200 and retry.json()["duplicate"] is True
    assert retry.json()["reading"]["id"] == original.json()["reading"]["id"]
    assert retry.json()["reading"]["batch_id"] == first["id"]
    changed = send(client, device, 1, gas_adc=2000)
    assert changed.status_code == 409


def test_legacy_firmware_payload_is_accepted_and_unassigned_readings_never_attach(client, headers):
    auth = headers("operator")
    batch = make_batch(client, auth, "batch-a")
    device = make_device(client, auth)
    legacy = send(client, device, 1, batch_id=batch["id"])
    assert legacy.status_code == 201
    assert legacy.json()["reading"]["batch_id"] is None  # server truth: no assignment yet
    client.post(
        f"/api/v1/devices/{device['id']}/assignment", headers=auth, json={"batch_id": batch["id"]}
    )
    # Earlier unattached readings must not appear in the batch retroactively.
    assert history(client, auth, batch)["total"] == 0
    assert (
        send(client, device, 2, batch_id=batch["id"]).json()["reading"]["batch_id"] == batch["id"]
    )


def test_disabled_device_cannot_send_or_be_assigned(client, headers):
    auth = headers("operator")
    batch = make_batch(client, auth, "batch-a")
    device = make_device(client, auth)
    off = client.patch(f"/api/v1/devices/{device['id']}", headers=auth, json={"active": False})
    assert off.status_code == 200
    assert send(client, device, 1).status_code == 401
    blocked = client.post(
        f"/api/v1/devices/{device['id']}/assignment", headers=auth, json={"batch_id": batch["id"]}
    )
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "device_disabled"


def test_baseline_can_be_recorded_before_the_device_joins_a_batch(client, headers):
    auth = headers("operator")
    device = make_device(client, auth)
    response = client.post(
        f"/api/v1/devices/{device['id']}/baseline",
        headers=auth,
        json={"gas_adc": 1000, "recorded_at": utcnow().isoformat()},
    )
    assert response.status_code == 201, response.text


def test_operators_run_the_device_lifecycle_and_vendors_cannot(client, headers):
    operator, vendor = headers("operator"), headers("vendor")
    device = make_device(client, operator)
    rotated = client.post(f"/api/v1/devices/{device['id']}/rotate-credential", headers=operator)
    assert rotated.status_code == 200 and rotated.json()["credential"] != device["credential"]
    batch = make_batch(client, operator, "batch-a")
    body = {"batch_id": batch["id"]}
    assert (
        client.post("/api/v1/devices", headers=vendor, json={"identifier": "v"}).status_code == 403
    )
    assert (
        client.post(
            f"/api/v1/devices/{device['id']}/assignment", headers=vendor, json=body
        ).status_code
        == 403
    )
    assert (
        client.delete(f"/api/v1/devices/{device['id']}/assignment", headers=vendor).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/devices/{device['id']}", headers=vendor, json={"active": False}
        ).status_code
        == 403
    )


def test_vendor_sees_only_devices_that_served_their_batches(client, headers):
    operator, vendor = headers("operator"), headers("vendor")
    shared = make_batch(client, operator, "shared", owner_id="vendor")
    private = make_batch(client, operator, "private")
    device = make_device(client, operator, batch_id=shared["id"])
    stranger = make_device(client, operator, identifier="never-theirs", batch_id=private["id"])
    unattached = make_device(client, operator, identifier="free")
    assert send(client, device, 1).status_code == 201
    assert send(client, stranger, 1).status_code == 201
    assert send(client, unattached, 1).status_code == 201

    def visible():
        return {d["id"] for d in client.get("/api/v1/devices", headers=vendor).json()["items"]}

    assert visible() == {device["id"]}
    assert client.get(f"/api/v1/devices/{stranger['id']}", headers=vendor).status_code == 404
    assert client.get(f"/api/v1/devices/{unattached['id']}", headers=vendor).status_code == 404

    # After the device moves to a batch the vendor does not own, history stays visible,
    # but the new batch's readings and assignments do not leak.
    client.post(
        f"/api/v1/devices/{device['id']}/assignment",
        headers=operator,
        json={"batch_id": private["id"], "replace": True},
    )
    assert send(client, device, 2).status_code == 201
    assert visible() == {device["id"]}
    seen = client.get(f"/api/v1/devices/{device['id']}/readings/latest", headers=vendor).json()
    assert seen["batch_id"] == shared["id"] and seen["gas_adc"] == 1001
    trail = client.get(f"/api/v1/devices/{device['id']}/assignments", headers=vendor).json()
    assert [a["batch_id"] for a in trail["items"]] == [shared["id"]]


def test_operators_share_batches_only_with_active_vendors(client, app, headers):
    operator, admin = headers("operator"), headers("admin")
    shared = make_batch(client, operator, "to-vendor", owner_id="vendor")
    assert shared["owner_id"] == "vendor"
    denied = client.post(
        "/api/v1/batches",
        headers=operator,
        json={**BATCH, "identifier": "to-admin", "owner_id": "admin"},
    )
    assert denied.status_code == 403
    missing = client.post(
        "/api/v1/batches",
        headers=operator,
        json={**BATCH, "identifier": "to-nobody", "owner_id": "nobody"},
    )
    assert missing.status_code == 403  # same answer as a non-vendor: no user-existence leak
    assert (
        make_batch(client, admin, "admin-to-operator", owner_id="operator")["owner_id"]
        == "operator"
    )

    mine = make_batch(client, operator, "mine")
    handed = client.patch(
        f"/api/v1/batches/{mine['id']}", headers=operator, json={"owner_id": "vendor"}
    )
    assert handed.status_code == 200 and handed.json()["owner_id"] == "vendor"
    refused = client.patch(
        f"/api/v1/batches/{mine['id']}", headers=operator, json={"owner_id": "admin"}
    )
    assert refused.status_code == 403
    assert (
        client.patch(
            f"/api/v1/batches/{mine['id']}", headers=headers("vendor"), json={"owner_id": "vendor"}
        ).status_code
        == 403
    )


def test_vendor_picker_lists_vendors_only_to_operators(client, headers):
    listing = client.get("/api/v1/vendors", headers=headers("operator"))
    assert listing.status_code == 200
    assert listing.json()["items"] == [{"id": "vendor", "user_id": "vendor"}]
    assert client.get("/api/v1/vendors", headers=headers("vendor")).status_code == 403
    assert client.get("/api/v1/vendors").status_code == 401


def test_assignment_audit_trail_is_written(client, app, headers):
    from app.db.models import DecisionLog

    auth = headers("operator")
    first, second = make_batch(client, auth, "batch-a"), make_batch(client, auth, "batch-b")
    device = make_device(client, auth, batch_id=first["id"])
    client.post(
        f"/api/v1/devices/{device['id']}/assignment",
        headers=auth,
        json={"batch_id": second["id"], "replace": True},
    )
    with app.state.session_factory() as db:
        kinds = set(db.scalars(select(DecisionLog.decision_type)))
        released_on = db.scalars(
            select(DecisionLog.batch_id).where(DecisionLog.decision_type == "device_released")
        ).all()
        stored = db.scalar(select(func.count()).select_from(SensorReading))
    assert {"device_registered", "device_assigned", "device_released"} <= kinds
    assert released_on == [first["id"]]  # the batch that lost the device records it
    assert stored == 0


@pytest.mark.parametrize("body", [{}, {"batch_id": ""}, {"batch_id": "x", "unknown": 1}])
def test_assignment_input_is_validated(client, headers, body):
    auth = headers("operator")
    device = make_device(client, auth)
    response = client.post(f"/api/v1/devices/{device['id']}/assignment", headers=auth, json=body)
    assert response.status_code == 422
    missing = client.post(
        f"/api/v1/devices/{device['id']}/assignment", headers=auth, json={"batch_id": "nope"}
    )
    assert missing.status_code == 404
