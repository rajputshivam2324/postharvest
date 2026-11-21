"""Test-only FastAPI fixture. Never loads .env or contacts Neon/Gemini."""

# ruff: noqa: E402 -- add the sibling backend to the import path before imports.

import secrets
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "backend"))
sys.path.insert(0, str(root))

import uvicorn
from fastapi.testclient import TestClient
from simulator.scenarios import generate
from sqlalchemy import create_engine, text

from app.core.config import Settings
from app.core.security import hash_password
from app.core.time import utcnow
from app.db.base import Base
from app.db.models import User
from app.db.session import session_factory
from app.main import create_app
from app.risk.policy import RiskPolicy

temporary = tempfile.TemporaryDirectory(prefix="harvest-e2e-")
settings = Settings(
    environment="test",
    database_url=f"sqlite:///{temporary.name}/fixture.db",
    jwt_secret=secrets.token_urlsafe(48),
    gemini_api_key=None,
    risk_policy=RiskPolicy(window_seconds=3600, min_samples=6),
    _env_file=None,
)
app = create_app(settings)
# The backend's unit-test StaticPool shares one SQLite connection. Browser
# requests are concurrent, so this file-backed fixture needs independent ones.
app.state.engine.dispose()
app.state.engine = create_engine(settings.sqlalchemy_url, connect_args={"check_same_thread": False})
app.state.session_factory = session_factory(app.state.engine)
Base.metadata.create_all(app.state.engine)
with app.state.engine.begin() as connection:
    connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
    connection.execute(text("INSERT INTO alembic_version VALUES ('0004')"))
with app.state.session_factory.begin() as db:
    for role in ("admin", "operator", "vendor"):
        db.add(
            User(
                id=role,
                user_id=role,
                role=role,
                password_hash=hash_password("frontend-test-password"),
            )
        )

# Test credentials apply only to this disposable loopback fixture.
with TestClient(app) as client:
    result = client.post(
        "/api/v1/auth/login", json={"user_id": "admin", "password": "frontend-test-password"}
    ).json()
    auth = {"Authorization": f"Bearer {result['access_token']}"}
    now = utcnow()
    for index, scenario in enumerate(("deterioration", "stable", "stale")):
        batch = client.post(
            "/api/v1/batches",
            headers=auth,
            json={
                "identifier": f"TOM-{index + 1:03d}",
                "commodity": "tomato",
                "quantity": 24 + index * 8,
                "unit": "kg",
                "storage_location": f"Bay {chr(65 + index)}",
                "owner_id": "vendor",
                "notes": "Synthetic scenario for frontend verification.",
            },
        ).json()
        device = client.post(
            "/api/v1/devices",
            headers=auth,
            json={"identifier": f"SIM-{index + 1:03d}", "batch_id": batch["id"], "simulated": True},
        ).json()
        client.post(
            f"/api/v1/devices/{device['id']}/baseline",
            headers=auth,
            json={"gas_adc": 1000, "recorded_at": (now - timedelta(hours=4)).isoformat()},
        )
        for reading in generate(
            scenario=scenario,
            seed=42,
            start=now - timedelta(hours=1),
            count=13,
            interval_seconds=300,
            batch_id=batch["id"],
            device_id=device["id"],
            run_id=f"fixture-{index}",
        ):
            client.post(
                "/api/v1/readings", headers={"X-Device-Token": device["credential"]}, json=reading
            )
        client.post(
            f"/api/v1/batches/{batch['id']}/observations",
            headers=auth,
            json={
                "condition": "Operator inspection recorded for this synthetic scenario.",
                "observed_at": (now - timedelta(minutes=20)).isoformat(),
            },
        )
        assessment = client.post(f"/api/v1/batches/{batch['id']}/assessments", headers=auth)
        assert assessment.status_code == 201

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8011, log_level="warning")
