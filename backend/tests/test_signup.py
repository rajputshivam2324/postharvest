import pytest
from sqlalchemy import select

from app.db.models import DecisionLog, User


@pytest.mark.parametrize("role", ["operator", "vendor"])
def test_signup_login_and_role_boundaries(client, app, role):
    payload = {"user_id": f"signup-{role}", "password": "a-new-test-password", "role": role}
    response = client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 201
    account = response.json()
    assert account["role"] == role
    assert "password" not in account and "password_hash" not in account
    login = client.post("/api/v1/auth/login", json={k: payload[k] for k in ("user_id", "password")})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=headers).json()["id"] == account["id"]
    assert client.get("/api/v1/users", headers=headers).status_code == 403
    batch = {
        "identifier": "signup-batch",
        "commodity": "tomato",
        "quantity": 1,
        "unit": "kg",
        "storage_location": "A",
    }
    assert client.post("/api/v1/batches", headers=headers, json=batch).status_code == (
        201 if role == "operator" else 403
    )
    with app.state.session_factory() as db:
        assert db.get(User, account["id"]).password_hash.startswith("$argon2id$")
        record = db.scalar(select(DecisionLog).where(DecisionLog.actor_id == account["id"]))
        assert record is not None and record.rationale == "Public self-registration"


def test_signup_defaults_to_vendor_and_rejects_admin(client):
    payload = {"user_id": "self-created", "password": "a-new-test-password"}
    assert client.post("/api/v1/auth/signup", json=payload).json()["role"] == "vendor"
    assert client.post("/api/v1/auth/signup", json=payload).status_code == 409
    for invalid in [
        {**payload, "role": "admin"},
        {**payload, "password": "short"},
        {**payload, "active": True},
        {**payload, "user_id": "bad user id"},
    ]:
        response = client.post("/api/v1/auth/signup", json=invalid)
        assert response.status_code == 422
        assert payload["password"] not in response.text


def test_signup_rate_limit(client, app):
    app.state.signup_limiter.limit = 1
    payload = {"user_id": "limited-signup", "password": "a-new-test-password"}
    assert client.post("/api/v1/auth/signup", json=payload).status_code == 201
    assert (
        client.post("/api/v1/auth/signup", json={**payload, "user_id": "second-signup"}).status_code
        == 429
    )
