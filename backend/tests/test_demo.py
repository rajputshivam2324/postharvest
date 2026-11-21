import json

from pydantic import SecretStr
from sqlalchemy import func, select

from app.ai.gemini import GeminiAdapter
from app.db.models import Batch, Device, DeviceBaseline, ExplanationJob, Observation, SensorReading
from app.worker import process_one


def test_demo_has_full_window_evidence_and_no_fake_ai(client, app, headers):
    response = client.post("/api/v1/demo/batches", headers=headers("operator"))
    assert response.status_code == 201, response.text
    demo = response.json()
    assert demo["simulated"] is True and demo["reading_count"] == 73
    assert demo["batch"]["identifier"].startswith("DEMO-TOMATO-")
    assert demo["batch"]["attributes"]["seeded_demo"] is True
    assert demo["assessment"]["score"] is not None
    assert demo["assessment"]["quality_flags"] == []
    assert demo["assessment"]["ai_status"] == "disabled"
    assert demo["assessment"]["ai_explanation"] is None
    assert "credential" not in response.text
    with app.state.session_factory() as db:
        device = db.scalar(select(Device).where(Device.batch_id == demo["batch"]["id"]))
        assert device is not None and device.simulated
        assert (
            db.scalar(
                select(func.count())
                .select_from(SensorReading)
                .where(SensorReading.device_id == device.id)
            )
            == 73
        )
        baseline = db.scalar(select(DeviceBaseline).where(DeviceBaseline.device_id == device.id))
        first = db.scalar(
            select(SensorReading)
            .where(SensorReading.device_id == device.id)
            .order_by(SensorReading.source_timestamp)
        )
        assert (
            baseline is not None
            and first is not None
            and baseline.recorded_at < first.source_timestamp
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(Observation)
                .where(Observation.batch_id == demo["batch"]["id"])
            )
            == 2
        )
    repeated = client.post("/api/v1/demo/batches", headers=headers())
    assert repeated.status_code == 201
    assert repeated.json()["batch"]["id"] != demo["batch"]["id"]


def test_demo_access_and_quality_failure_leave_no_records(client, app, headers):
    assert client.post("/api/v1/demo/batches").status_code == 401
    assert client.post("/api/v1/demo/batches", headers=headers("vendor")).status_code == 403
    app.state.settings.risk_policy.commodity = "apple"
    assert client.post("/api/v1/demo/batches", headers=headers()).status_code == 422
    assert client.get("/api/v1/batches", headers=headers()).json()["total"] == 0
    app.state.settings.risk_policy.commodity = "tomato"
    app.state.settings.risk_policy.min_samples = 73
    assert client.post("/api/v1/demo/batches", headers=headers()).status_code == 422
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Batch)) == 0
        assert db.scalar(select(func.count()).select_from(Device)) == 0


def test_selected_demo_job_uses_real_adapter_boundary_without_draining_other_jobs(
    client, app, headers, monkeypatch
):
    app.state.settings.gemini_api_key = SecretStr("unused-test-key")
    auth = headers()
    older = client.post("/api/v1/demo/batches", headers=auth).json()
    chosen = client.post("/api/v1/demo/batches", headers=auth).json()
    assert chosen["assessment"]["ai_job_status"] == "pending"

    def generate(self, context):
        return json.dumps(
            {
                "status": context["status"],
                "risk_interpretation": "Synthetic rising response warrants a human inspection.",
                "evidence_ids": [context["evidence"][0]["id"]],
                "suggested_next_step": "Inspect and compare with real observations.",
                "uncertainty": "Synthetic evidence and uncalibrated gas response "
                "cannot establish actual condition.",
                "human_review_required": True,
            }
        )

    monkeypatch.setattr(GeminiAdapter, "generate", generate)
    monkeypatch.setattr(
        GeminiAdapter,
        "embed",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("embedding unavailable")),
    )
    assert process_one(
        app.state.session_factory, app.state.settings, assessment_id=chosen["assessment"]["id"]
    )
    result = client.get(f"/api/v1/batches/{chosen['batch']['id']}/assessment", headers=auth).json()
    assert result["ai_status"] == "ok"
    assert result["cited_evidence_ids"] and result["ai_explanation"]["human_review_required"]
    with app.state.session_factory() as db:
        old_job = db.scalar(
            select(ExplanationJob).where(ExplanationJob.assessment_id == older["assessment"]["id"])
        )
        assert old_job is not None and old_job.status == "pending"
