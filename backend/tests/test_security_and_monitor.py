import pytest
from sqlalchemy import func, select

from app.core.errors import DomainError
from app.core.rate_limit import LoginLimiter
from app.db.models import DecisionLog, RiskAssessment
from app.monitor import run_once


def test_login_rate_limit():
    limiter = LoginLimiter(limit=2, window_seconds=60)
    limiter.check("local-client")
    limiter.check("local-client")
    with pytest.raises(DomainError) as exc:
        limiter.check("local-client")
    assert exc.value.status_code == 429
    limiter.check("another-client")


def test_all_application_routes_require_user_auth(client, app):
    # Public by design: login, signup, device ingestion (device token), and the pairing claim
    # (single-use code, rate limited). Everything else needs a user.
    allowed = {
        "/api/v1/auth/login",
        "/api/v1/auth/signup",
        "/api/v1/readings",
        "/api/v1/pairing/claim",
    }
    checked = 0
    for route_path, operations in app.openapi()["paths"].items():
        if not route_path.startswith("/api/v1") or route_path in allowed:
            continue
        path = (
            route_path.replace("{batch_id}", "unavailable")
            .replace("{device_id}", "unavailable")
            .replace("{alert_id}", "unavailable")
            .replace("{user_id}", "unavailable")
        )
        for method in (name.upper() for name in operations):
            if method in {"GET", "POST", "PATCH", "DELETE"}:
                response = client.request(method, path, json={} if method != "GET" else None)
                assert response.status_code == 401, (method, route_path, response.text)
                checked += 1
    assert checked >= 30


def test_monitor_records_actor_and_includes_missing_devices(client, app, monitoring):
    batch, _, auth = monitoring
    count = run_once(app.state.session_factory, app.state.settings, "admin")
    assert count == 1
    with app.state.session_factory() as db:
        assessment = db.scalars(select(RiskAssessment)).one()
        assert assessment.actor_id == "admin"
        assert assessment.status == "insufficient_data"
        assert db.scalar(select(func.count()).select_from(DecisionLog)) > 0
    with pytest.raises(DomainError):
        run_once(app.state.session_factory, app.state.settings, "vendor")
    client.post(f"/api/v1/batches/{batch['id']}/archive", headers=auth)
    assert run_once(app.state.session_factory, app.state.settings, "admin") == 0
