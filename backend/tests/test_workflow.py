import json

import pytest

from app.ai.gemini import GeminiAdapter
from app.ai.schema import validate_explanation
from app.core.config import Settings
from app.retrieval.query import EvidenceItem
from app.workflow.explanation import build_workflow


def output(**overrides):
    return json.dumps(
        {
            "status": "fresh",
            "risk_interpretation": "Observed conditions are stable.",
            "evidence_ids": ["evidence-1"],
            "suggested_next_step": "Inspect the batch.",
            "uncertainty": "Gas readings are uncalibrated; human observation is required.",
            "human_review_required": True,
            **overrides,
        }
    )


def enabled_adapter():
    return GeminiAdapter(
        Settings(
            environment="test",
            database_url="sqlite://",
            jwt_secret="x" * 40,
            gemini_api_key="unused-test-key",
            _env_file=None,
        )
    )


def test_validated_workflow_node_order(monkeypatch):
    adapter = enabled_adapter()
    contexts = []

    def generate(context):
        contexts.append(context)
        return output()

    monkeypatch.setattr(adapter, "generate", generate)
    graph = build_workflow(
        adapter, lambda: [EvidenceItem(id="evidence-1", source_type="observation", text="Firm")]
    )
    result = graph.invoke({"status": "fresh", "score": 1, "features": {"simulated": True}})
    assert result["ai_status"] == "ok"
    assert result["output"]["human_review_required"] is True
    assert result["visited"] == [
        "load_features",
        "quality_gate",
        "retrieve_evidence",
        "explain",
        "validate",
        "fallback",
    ]
    assert contexts[0]["status"] == "fresh"


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        output(evidence_ids=["invented"]),
        output(status="spoiling"),
        output(human_review_required=False),
        output(risk_interpretation="This batch is safe to eat."),
        output(risk_interpretation="Shelf life is 5 days."),
        output(extra_field="arbitrary"),
        output(evidence_ids=["evidence-1", "evidence-1"]),
    ],
)
def test_invalid_output_falls_back(monkeypatch, raw):
    adapter = enabled_adapter()
    monkeypatch.setattr(adapter, "generate", lambda context: raw)
    result = build_workflow(
        adapter, lambda: [EvidenceItem(id="evidence-1", source_type="episode_summary", text="data")]
    ).invoke({"status": "fresh", "score": 1, "features": {}})
    assert result["ai_status"] == "invalid_output"
    assert result["output"] is None


def test_disabled_quality_and_provider_failure(monkeypatch):
    adapter = enabled_adapter()
    monkeypatch.setattr(adapter, "generate", lambda context: (_ for _ in ()).throw(TimeoutError()))

    def evidence():
        return [EvidenceItem(id="evidence-1", source_type="observation", text="data")]

    failed = build_workflow(adapter, evidence).invoke(
        {"status": "fresh", "score": 1, "features": {}}
    )
    assert failed["ai_status"] == "failed"
    insufficient = build_workflow(
        adapter, lambda: pytest.fail("Retrieval should be skipped")
    ).invoke({"status": "insufficient_data", "score": None, "features": {}})
    assert insufficient["visited"] == ["load_features", "quality_gate", "fallback"]
    disabled = GeminiAdapter(
        Settings(environment="test", database_url="sqlite://", jwt_secret="x" * 40, _env_file=None)
    )
    result = build_workflow(disabled, lambda: pytest.fail("Retrieval should be skipped")).invoke(
        {"status": "fresh", "score": 1, "features": {}}
    )
    assert result["ai_status"] == "disabled"


def test_empty_evidence_cannot_generate(monkeypatch):
    adapter = enabled_adapter()
    monkeypatch.setattr(adapter, "generate", lambda context: pytest.fail("No evidence supplied"))
    result = build_workflow(adapter, lambda: []).invoke(
        {"status": "fresh", "score": 1, "features": {}}
    )
    assert result["ai_status"] == "failed"


def test_schema_requires_citations():
    with pytest.raises(ValueError):
        validate_explanation(output(evidence_ids=[]), supplied_ids=set(), status="fresh")
