import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

from app.core.config import Settings
from app.core.security import hash_password
from app.db.base import Base
from app.db.models import User
from app.main import create_app


@pytest.fixture
def app():
    settings = Settings(
        environment="test", database_url="sqlite://", jwt_secret="t" * 48, _env_file=None
    )
    app = create_app(settings)
    event.listen(
        app.state.engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(app.state.engine)
    with app.state.engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('0006')"))
    encoded = hash_password("a-valid-test-password")
    with app.state.session_factory.begin() as db:
        for role in ["admin", "operator", "vendor"]:
            db.add(User(id=role, user_id=role, password_hash=encoded, role=role))
    return app


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def headers(client):
    def login(role="admin"):
        response = client.post(
            "/api/v1/auth/login", json={"user_id": role, "password": "a-valid-test-password"}
        )
        assert response.status_code == 200
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    return login


@pytest.fixture
def monitoring(client, headers):
    auth = headers()
    batch = client.post(
        "/api/v1/batches",
        headers=auth,
        json={
            "identifier": "tomatoes-1",
            "commodity": "tomato",
            "quantity": 10,
            "unit": "kg",
            "storage_location": "carton A",
        },
    )
    assert batch.status_code == 201, batch.text
    device = client.post(
        "/api/v1/devices",
        headers=auth,
        json={"identifier": "esp32-1", "batch_id": batch.json()["id"], "simulated": True},
    )
    assert device.status_code == 201, device.text
    return batch.json(), device.json(), auth
