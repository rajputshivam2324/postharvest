import json
from datetime import timedelta

import pytest
from pydantic import SecretStr
from simulator.scenarios import generate
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.ai.gemini import GeminiAdapter
from app.core.time import utcnow
from app.db.models import Alert, Batch, EvidenceChunk, ExplanationJob, RiskAssessment, User
from app.retrieval.query import retrieve
from app.risk.policy import RiskPolicy
from app.worker import claim, finish, process_one


def fill_window(client, app, monitoring, scenario="stable"):
    batch, device, auth = monitoring
    app.state.settings.risk_policy = RiskPolicy(window_seconds=3600, min_samples=6)
    now = utcnow()
    baseline = client.post(
        f"/api/v1/devices/{device['id']}/baseline",
        headers=auth,
        json={"gas_adc": 1000, "recorded_at": (now - timedelta(hours=2)).isoformat()},
    )
    assert baseline.status_code == 201, baseline.text
    rows = generate(
        scenario=scenario,
        seed=42,
        start=now - timedelta(hours=1),
        count=13,
        interval_seconds=300,
        batch_id=batch["id"],
        device_id=device["id"],
        run_id="risk-run",
    )
    for payload in rows:
        response = client.post(
            "/api/v1/readings", json=payload, headers={"X-Device-Token": device["credential"]}
        )
        assert response.status_code == 201, response.text
    return batch, device, auth


def test_full_pipeline_assessment_alert_dedup_and_audit(client, app, monitoring):
    batch, _, auth = fill_window(client, app, monitoring, "deterioration")
    path = f"/api/v1/batches/{batch['id']}/assessments"
    first = client.post(path, headers=auth)
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "spoiling"
    assert first.json()["ai_status"] == "disabled"
    assert first.json()["human_review_required"] is True
    assert client.post(path, headers=auth).status_code == 201
    alerts = client.get("/api/v1/alerts", headers=auth).json()
    assert alerts["total"] == 1
    alert = alerts["items"][0]
    assert alert["delivery_status"] == "mocked"
    ack = client.post(f"/api/v1/alerts/{alert['id']}/acknowledge", headers=auth)
    assert ack.status_code == 200
    assert ack.json()["resolved_at"] is None
    assert client.post(path, headers=auth).status_code == 201
    assert client.get("/api/v1/alerts", headers=auth).json()["total"] == 1
    attempts = client.get(f"/api/v1/alerts/{alert['id']}/attempts", headers=auth).json()
    assert attempts["total"] == 1
    assert attempts["items"][0]["provider"] == "mock"
    decisions = client.get(f"/api/v1/batches/{batch['id']}/decisions", headers=auth).json()
    assert "state_transition" in {item["decision_type"] for item in decisions["items"]}
    assert client.get(f"/api/v1/batches/{batch['id']}/assessment", headers=auth).status_code == 200


def test_stable_and_insufficient_pipeline(client, app, monitoring):
    batch, _, auth = monitoring
    path = f"/api/v1/batches/{batch['id']}/assessments"
    insufficient = client.post(path, headers=auth)
    assert insufficient.json()["status"] == "insufficient_data"
    fill_window(client, app, monitoring)
    stable = client.post(path, headers=auth)
    assert stable.json()["status"] == "fresh", stable.text
    assert client.get("/api/v1/alerts?resolved=false", headers=auth).json()["total"] == 0
    assert client.get("/api/v1/alerts?resolved=true", headers=auth).json()["total"] == 1


def test_priorities_reproducibility_factors_and_annotations(client, monitoring):
    batch, _, auth = monitoring
    assert client.get("/api/v1/priorities", headers=auth).json()["ranking_meaningful"] is False
    second = client.post(
        "/api/v1/batches",
        headers=auth,
        json={
            "identifier": "batch-2",
            "commodity": "tomato",
            "quantity": 2,
            "unit": "kg",
            "storage_location": "B",
        },
    )
    assert second.status_code == 201
    first = client.get("/api/v1/priorities", headers=auth).json()
    assert first == client.get("/api/v1/priorities", headers=auth).json()
    assert first["ranking_meaningful"] is True
    assert first["items"][0]["score"] == sum(first["items"][0]["factors"].values())
    decision = client.post(
        f"/api/v1/batches/{batch['id']}/decisions",
        headers=auth,
        json={
            "decision_type": "priority_override",
            "rationale": "Inspection requested",
            "override_rank": 1,
        },
    )
    assert decision.status_code == 201
    assert decision.json()["input_references"]["override_rank"] == 1
    priorities = client.get("/api/v1/priorities", headers=auth).json()
    overridden = next(item for item in priorities["items"] if item["batch_id"] == batch["id"])
    assert overridden["override_rank"] == 1
    assert overridden["override_record_id"] == decision.json()["id"]
    assert overridden["rank"] == 1
    assert (
        client.post(
            f"/api/v1/batches/{batch['id']}/decisions",
            headers=auth,
            json={"decision_type": "priority_override", "rationale": "Cleared override"},
        ).status_code
        == 201
    )
    priorities = client.get("/api/v1/priorities", headers=auth).json()
    assert all(item["override_rank"] is None for item in priorities["items"])


def test_retrieval_scope_and_budget(client, app, monitoring, headers):
    batch, _, auth = monitoring
    client.post(f"/api/v1/batches/{batch['id']}/assessments", headers=auth)
    vendor = headers("vendor")
    assert client.get(f"/api/v1/batches/{batch['id']}/evidence", headers=vendor).status_code == 404
    with app.state.session_factory.begin() as db:
        other = Batch(
            id="foreign",
            identifier="foreign",
            owner_id="vendor",
            commodity="tomato",
            quantity=1,
            unit="kg",
            storage_location="secret",
        )
        db.add(other)
        db.flush()
        db.add(
            EvidenceChunk(
                source_type="observation",
                source_reference="foreign-obs",
                batch_id="foreign",
                commodity="tomato",
                text="PRIVATE",
                content_hash="a" * 64,
            )
        )
    with app.state.session_factory() as db:
        admin = db.get(User, "admin")
        result = retrieve(
            db, batch_id=batch["id"], actor=admin, at=utcnow(), settings=app.state.settings
        )
        assert result
        assert all("PRIVATE" not in item.text for item in result)
        assert (
            sum(len(item.text) for item in result) <= app.state.settings.retrieval_token_budget * 3
        )
        assert len(result) <= app.state.settings.retrieval_top_k
        assert (
            len(json.dumps([item.model_dump() for item in result]).encode())
            <= app.state.settings.retrieval_token_budget
        )


def test_durable_worker_keeps_deterministic_result(monkeypatch, client, app, monitoring):
    batch, _, auth = fill_window(client, app, monitoring)
    app.state.settings.gemini_api_key = SecretStr("unused-test-key")
    assessment = client.post(f"/api/v1/batches/{batch['id']}/assessments", headers=auth).json()
    assert assessment["ai_job_status"] == "pending"

    def generate(context):
        return json.dumps(
            {
                "status": context["status"],
                "risk_interpretation": "Stable structured evidence.",
                "evidence_ids": [context["evidence"][0]["id"]],
                "suggested_next_step": "Inspect the batch.",
                "uncertainty": "Signals are uncalibrated.",
                "human_review_required": True,
            }
        )

    monkeypatch.setattr(GeminiAdapter, "generate", lambda self, context: generate(context))
    monkeypatch.setattr(GeminiAdapter, "embed", lambda self, text, **kwargs: [1.0] + [0.0] * 767)
    assert process_one(app.state.session_factory, app.state.settings) is True
    assert process_one(app.state.session_factory, app.state.settings) is False
    updated = client.get(f"/api/v1/batches/{batch['id']}/assessment", headers=auth).json()
    assert updated["ai_status"] == "ok", updated
    assert updated["ai_explanation"]["evidence_ids"] == updated["cited_evidence_ids"]
    assert updated["status"] == assessment["status"]
    assert updated["explanation"] == assessment["explanation"]


def test_worker_failure_and_stale_lease(monkeypatch, client, app, monitoring):
    batch, _, auth = fill_window(client, app, monitoring)
    app.state.settings.gemini_api_key = SecretStr("unused-test-key")
    response = client.post(f"/api/v1/batches/{batch['id']}/assessments", headers=auth)
    assert response.status_code == 201
    first_id, first_token = claim(app.state.session_factory, app.state.settings)
    with app.state.session_factory.begin() as db:
        db.get(ExplanationJob, first_id).locked_at = utcnow() - timedelta(hours=1)
    second_id, second_token = claim(app.state.session_factory, app.state.settings)
    assert first_id == second_id and first_token != second_token
    finish(
        app.state.session_factory,
        app.state.settings,
        first_id,
        first_token,
        {"ai_status": "ok", "output": None},
    )
    with app.state.session_factory() as db:
        assert db.get(ExplanationJob, first_id).status == "running"
    finish(
        app.state.session_factory,
        app.state.settings,
        second_id,
        second_token,
        {"ai_status": "failed", "output": None},
    )
    with app.state.session_factory() as db:
        assessment = db.get(RiskAssessment, response.json()["id"])
        assert assessment.ai_status == "failed"
        assert assessment.status == "fresh"


def test_alert_database_uniqueness(client, app, monitoring):
    batch, _, auth = monitoring
    client.post(f"/api/v1/batches/{batch['id']}/assessments", headers=auth)
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Alert)) == 1
    with pytest.raises(IntegrityError):
        with app.state.session_factory.begin() as db:
            original = db.scalars(select(Alert)).one()
            db.add(
                Alert(
                    batch_id=original.batch_id,
                    assessment_id=original.assessment_id,
                    trigger_key=original.trigger_key,
                    severity="warning",
                    message="Duplicate",
                )
            )
            db.flush()
