from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core.config import Settings
from app.core.rate_limit import LoginLimiter
from app.core.security import PAIRING_ALPHABET, pairing_code_hash
from app.core.time import utcnow
from app.db.models import DecisionLog, Device, PairingCode

CLAIM = "/api/v1/pairing/claim"


def register(client, auth, identifier="esp32-new", **extra):
    response = client.post(
        "/api/v1/devices/pairing",
        headers=auth,
        json={"identifier": identifier, "simulated": True, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def claim(client, code):
    return client.post(CLAIM, json={"code": code})


def reading(device_id, n=1):
    return {
        "device_id": device_id,
        "event_id": f"pair-{n}",
        "temperature_c": 21,
        "humidity_pct": 70,
        "gas_adc": 1000,
        "gas_voltage_v": 0.8,
        "source_timestamp": utcnow().isoformat(),
        "simulated": True,
    }


def test_new_device_pairs_with_a_code_and_then_reports(client, headers):
    auth = headers("operator")
    device = register(client, auth)
    assert device["paired_at"] is None and device["connection_status"] == "unpaired"
    assert "credential" not in device
    code = device["pairing_code"]
    assert len(code) == 9 and code[4] == "-" and set(code.replace("-", "")) <= set(PAIRING_ALPHABET)

    # Until it pairs, the device has no way to authenticate, whatever it guesses.
    guess = {"X-Device-Token": "x" * 43}
    assert (
        client.post("/api/v1/readings", json=reading(device["id"]), headers=guess).status_code
        == 401
    )

    claimed = claim(client, code)
    assert claimed.status_code == 200, claimed.text
    body = claimed.json()
    assert body["device_id"] == device["id"] and body["identifier"] == "esp32-new"
    assert body["simulated"] is True and body["sampling_seconds"] > 0
    assert claimed.headers["cache-control"] == "no-store"  # a credential must not be cached

    sent = client.post(
        "/api/v1/readings",
        json=reading(device["id"]),
        headers={"X-Device-Token": body["credential"]},
    )
    assert sent.status_code == 201, sent.text
    seen = client.get(f"/api/v1/devices/{device['id']}", headers=auth).json()
    assert seen["paired_at"] and seen["connection_status"] == "online"
    assert "credential" not in str(seen)


def test_a_code_works_once(client, headers):
    device = register(client, headers("operator"))
    assert claim(client, device["pairing_code"]).status_code == 200
    again = claim(client, device["pairing_code"])
    assert again.status_code == 404 and again.json()["error"]["code"] == "invalid_pairing_code"


@pytest.mark.parametrize(
    "style",
    [str.lower, lambda c: c.replace("-", ""), lambda c: c.replace("-", " "), lambda c: f"  {c}  "],
)
def test_codes_survive_the_way_people_type_them(client, headers, style):
    device = register(client, headers("operator"))
    assert claim(client, style(device["pairing_code"])).status_code == 200


@pytest.mark.parametrize(
    "bad",
    ["ABCD", "ABCD-EFGH-JKMN", "0000-0000", "ILOU-ILOU", "ABCD-EFG!", "ZZZZ-ZZZZ", "a" * 32],
)
def test_every_kind_of_wrong_code_gets_the_same_answer(client, headers, bad):
    register(client, headers("operator"))
    response = claim(client, bad)
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "This code is not valid or has expired"


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_code_is_a_validation_error(client, blank):
    assert client.post(CLAIM, json={"code": blank}).status_code == 422


def test_expired_codes_are_refused(client, app, headers):
    device = register(client, headers("operator"))
    with app.state.session_factory.begin() as db:
        db.execute(update(PairingCode).values(expires_at=utcnow() - timedelta(seconds=1)))
    assert claim(client, device["pairing_code"]).status_code == 404
    with app.state.session_factory() as db:
        assert db.get(Device, device["id"]).paired_at is None


def test_only_the_newest_code_works(client, headers):
    auth = headers("operator")
    device = register(client, auth)
    fresh = client.post(f"/api/v1/devices/{device['id']}/pairing", headers=auth)
    assert fresh.status_code == 201 and fresh.json()["device_id"] == device["id"]
    assert claim(client, device["pairing_code"]).status_code == 404
    assert claim(client, fresh.json()["pairing_code"]).status_code == 200


def test_repairing_a_working_device_causes_no_downtime(client, headers):
    auth = headers("operator")
    device = register(client, auth)
    first = claim(client, device["pairing_code"]).json()["credential"]
    old = {"X-Device-Token": first}
    assert (
        client.post("/api/v1/readings", json=reading(device["id"], 1), headers=old).status_code
        == 201
    )

    code = client.post(f"/api/v1/devices/{device['id']}/pairing", headers=auth).json()[
        "pairing_code"
    ]
    # A new code is outstanding, but the device keeps working on its current credential.
    assert (
        client.post("/api/v1/readings", json=reading(device["id"], 2), headers=old).status_code
        == 201
    )
    second = claim(client, code).json()["credential"]
    assert second != first
    new = {"X-Device-Token": second}
    assert (
        client.post("/api/v1/readings", json=reading(device["id"], 3), headers=old).status_code
        == 401
    )
    assert (
        client.post("/api/v1/readings", json=reading(device["id"], 3), headers=new).status_code
        == 201
    )


def test_a_disabled_device_can_neither_get_nor_use_a_code(client, headers):
    auth = headers("operator")
    device = register(client, auth)
    client.patch(f"/api/v1/devices/{device['id']}", headers=auth, json={"active": False})
    assert claim(client, device["pairing_code"]).status_code == 404
    blocked = client.post(f"/api/v1/devices/{device['id']}/pairing", headers=auth)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "device_disabled"


def test_device_can_be_assigned_to_a_batch_while_pairing(client, headers):
    auth = headers("operator")
    batch = client.post(
        "/api/v1/batches",
        headers=auth,
        json={
            "identifier": "b1",
            "commodity": "tomato",
            "quantity": 1,
            "unit": "kg",
            "storage_location": "A",
        },
    ).json()
    device = register(client, auth, batch_id=batch["id"])
    assert device["batch_id"] == batch["id"]
    credential = claim(client, device["pairing_code"]).json()["credential"]
    sent = client.post(
        "/api/v1/readings", json=reading(device["id"]), headers={"X-Device-Token": credential}
    )
    assert sent.json()["reading"]["batch_id"] == batch["id"]
    unknown = client.post(
        "/api/v1/devices/pairing",
        headers=auth,
        json={"identifier": "ghost", "batch_id": "missing"},
    )
    assert unknown.status_code == 404
    assert (
        client.get("/api/v1/devices?unassigned=true", headers=auth).json()["total"] == 0
    )  # no half-made device


def test_claim_is_rate_limited_per_address(client, app, headers):
    register(client, headers("operator"))
    app.state.pairing_limiter = LoginLimiter(3, 60, action="pairing")
    assert [claim(client, "AAAA-AAAA").status_code for _ in range(3)] == [404, 404, 404]
    limited = claim(client, "AAAA-AAAA")
    assert limited.status_code == 429


def test_only_a_keyed_hash_of_the_code_is_stored(client, app, headers):
    device = register(client, headers("operator"))
    plain = device["pairing_code"].replace("-", "")
    with app.state.session_factory() as db:
        row = db.scalars(select(PairingCode)).one()
    assert row.code_hash != plain and plain not in row.code_hash and len(row.code_hash) == 64
    other = Settings(
        environment="test", database_url="sqlite://", jwt_secret="y" * 40, _env_file=None
    )
    assert pairing_code_hash(plain, app.state.settings) == row.code_hash
    assert (
        pairing_code_hash(plain, other) != row.code_hash
    )  # a stolen database cannot be brute-forced


def test_pairing_is_for_operators_only_and_is_audited(client, app, headers):
    operator, vendor = headers("operator"), headers("vendor")
    assert (
        client.post("/api/v1/devices/pairing", headers=vendor, json={"identifier": "v"}).status_code
        == 403
    )
    assert client.post("/api/v1/devices/pairing", json={"identifier": "v"}).status_code == 401
    device = register(client, operator)
    assert client.post(f"/api/v1/devices/{device['id']}/pairing", headers=vendor).status_code == 403
    assert client.post(f"/api/v1/devices/{device['id']}/pairing").status_code == 401
    claim(client, device["pairing_code"])
    with app.state.session_factory() as db:
        kinds = {(d.decision_type, d.actor_id) for d in db.scalars(select(DecisionLog))}
        stored = " ".join(
            d.rationale + str(d.input_references) for d in db.scalars(select(DecisionLog))
        )
    assert ("device_pairing_issued", "operator") in kinds and ("device_paired", None) in kinds
    assert device["pairing_code"].replace("-", "") not in stored


def test_duplicate_identifier_is_a_clean_conflict(client, headers):
    auth = headers("operator")
    register(client, auth, identifier="same")
    again = client.post("/api/v1/devices/pairing", headers=auth, json={"identifier": "same"})
    assert again.status_code == 409
