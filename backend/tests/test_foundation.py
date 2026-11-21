import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def test_health_and_unmigrated_readiness():
    settings = Settings(environment="test", database_url="sqlite://", jwt_secret="x" * 40)
    with TestClient(create_app(settings)) as client:
        response = client.get("/health")
        assert response.json() == {"status": "ok"}
        assert response.headers["X-Request-ID"]
        assert client.get("/ready").status_code == 503


def test_configuration_requires_secrets_and_postgres():
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql://localhost/harvest", jwt_secret="short")
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite://", jwt_secret="x" * 40)
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            database_url="postgresql://localhost/harvest",
            jwt_secret="x" * 40,
        )


def test_neon_url_preserves_tls_and_uses_psycopg():
    settings = Settings(
        database_url="postgresql://u:p@host/db?sslmode=require&channel_binding=require",
        jwt_secret="x" * 40,
    )
    assert settings.sqlalchemy_url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in settings.sqlalchemy_url
    assert "channel_binding=require" in settings.sqlalchemy_url
