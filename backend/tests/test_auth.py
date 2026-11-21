from datetime import timedelta

import jwt
import pytest
from sqlalchemy import event

from app.core.time import utcnow
from app.db.models import User


def test_login_me_and_password_storage(client, app, headers):
    response = client.get("/api/v1/auth/me", headers=headers())
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert "password_hash" not in response.json()
    with app.state.session_factory() as db:
        assert db.get(User, "admin").password_hash.startswith("$argon2id$")
    assert client.get("/ready").status_code == 200


def test_login_returns_profile_with_one_query(client, app):
    statements = []

    def record_query(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(app.state.engine, "before_cursor_execute", record_query)
    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"user_id": "operator", "password": "a-valid-test-password"},
        )
    finally:
        event.remove(app.state.engine, "before_cursor_execute", record_query)

    assert response.status_code == 200
    result = response.json()
    assert len(statements) == 1
    assert (
        result["user"]
        == client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {result['access_token']}"}
        ).json()
    )
    assert "password_hash" not in response.text
    assert result["token_type"] == "bearer"
    assert result["expires_in"] > 0
    assert result["expires_at"]


@pytest.mark.parametrize("header", [None, "Basic abc", "Bearer malformed", "Bearer "])
def test_invalid_tokens(client, header):
    assert (
        client.get(
            "/api/v1/batches", headers={"Authorization": header} if header else {}
        ).status_code
        == 401
    )


def test_expired_missing_claims_and_wrong_signature(client, app):
    now = utcnow()
    base = {
        "sub": "admin",
        "iat": now - timedelta(hours=1),
        "nbf": now - timedelta(hours=1),
        "exp": now - timedelta(seconds=1),
        "iss": "harvest-monitor",
        "aud": "harvest-api",
        "jti": "id",
    }
    secret = app.state.settings.jwt_secret.get_secret_value()
    for claims, key in [
        (base, secret),
        ({"sub": "admin"}, secret),
        ({**base, "exp": now + timedelta(hours=1)}, "different-secret" * 3),
    ]:
        token = jwt.encode(claims, key, algorithm="HS256")
        assert (
            client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
            == 401
        )


def test_generic_credentials_and_disabled_user(client, headers):
    for name in ["admin", "nonexistent"]:
        response = client.post("/api/v1/auth/login", json={"user_id": name, "password": "wrong"})
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Invalid credentials"
    operator_token = headers("operator")
    assert (
        client.patch(
            "/api/v1/users/operator", headers=headers(), json={"active": False}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/auth/me", headers=operator_token).status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"user_id": "operator", "password": "a-valid-test-password"},
        ).status_code
        == 401
    )


def test_user_management_roles_and_duplicates(client, headers):
    payload = {"user_id": "new-user", "password": "an-example-test-password", "role": "vendor"}
    assert (
        client.post("/api/v1/users", headers=headers("operator"), json=payload).status_code == 403
    )
    assert client.post("/api/v1/users", headers=headers(), json=payload).status_code == 201
    assert client.post("/api/v1/users", headers=headers(), json=payload).status_code == 409
    response = client.post(
        "/api/v1/auth/login", json={"user_id": "admin", "password": "SECRET", "extra": True}
    )
    assert response.status_code == 422
    assert "SECRET" not in response.text
