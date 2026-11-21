import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from scripts import live_smoke


def test_live_report_does_not_echo_credentials_or_provider_messages():
    secret = "credential-that-must-not-appear"
    original = RuntimeError(f"Cannot resolve postgresql://user:{secret}@private-host/db")
    error = OperationalError("SELECT 1", {}, original)
    result = live_smoke.failure(error)
    assert result["category"] == "dns_unavailable"
    assert secret not in str(result)
    assert "private-host" not in str(result)


def test_live_report_checks_both_providers_after_neon_failure(monkeypatch, app):
    monkeypatch.setattr(live_smoke, "build_engine", lambda settings: create_engine("sqlite://"))

    def unavailable(*args):
        raise ConnectionError("Outbound connection unavailable")

    monkeypatch.setattr(live_smoke, "database_flow", unavailable)
    calls = []

    def embed(self, text):
        calls.append("embedding")
        raise ConnectionError("Provider network unavailable")

    def generate(self, context):
        calls.append("explanation")
        raise ConnectionError("Provider network unavailable")

    monkeypatch.setattr(live_smoke.GeminiAdapter, "embed", embed)
    monkeypatch.setattr(live_smoke.GeminiAdapter, "generate", generate)
    result = live_smoke.run(app.state.settings)
    assert result["status"] == "failed"
    assert calls == ["embedding", "explanation"]
    assert set(result["checks"]) == {"neon_connectivity", "gemini_embedding", "gemini_explanation"}


def test_live_http_assertions_do_not_echo_response_secrets():
    from httpx import Response

    response = Response(500, json={"password": "sensitive-value"})
    with pytest.raises(ValueError) as exc:
        live_smoke.expect(response, 200)
    assert "sensitive-value" not in str(exc.value)
