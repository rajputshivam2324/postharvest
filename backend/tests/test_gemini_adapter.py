import json

import httpx
from google import genai
from google.genai import types

from app.ai.gemini import GeminiAdapter, generation_schema
from app.ai.schema import Explanation, validate_explanation
from app.core.config import Settings


def test_generation_schema_keeps_local_true_constraint():
    wire = generation_schema()
    assert wire["properties"]["human_review_required"]["type"] == "boolean"
    assert "const" not in wire["properties"]["human_review_required"]
    assert Explanation.model_json_schema()["properties"]["human_review_required"]["const"] is True


def test_real_sdk_serializes_request_before_network_boundary(monkeypatch):
    response = {
        "status": "fresh",
        "risk_interpretation": "Stable observed conditions.",
        "evidence_ids": ["evidence-1"],
        "suggested_next_step": "Inspect the batch.",
        "uncertainty": "The gas response is uncalibrated.",
        "human_review_required": True,
    }
    requests = []

    def handle(request):
        payload = json.loads(request.content)
        assert payload["generationConfig"]["maxOutputTokens"] == 3000
        thinking = payload["generationConfig"]["thinkingConfig"]
        assert thinking.get("thinkingBudget", thinking.get("thinking_budget")) == 512
        review = payload["generationConfig"]["responseSchema"]["properties"][
            "human_review_required"
        ]
        assert review["type"] == "BOOLEAN"
        assert "const" not in review
        requests.append(payload)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": json.dumps(response)}]},
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    sdk = genai.Client(
        api_key="unused-test-key",
        http_options=types.HttpOptions(
            httpx_client=httpx.Client(transport=httpx.MockTransport(handle)),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    adapter = GeminiAdapter(
        Settings(
            environment="test",
            database_url="sqlite://",
            jwt_secret="x" * 40,
            gemini_api_key="unused-test-key",
            _env_file=None,
        )
    )
    monkeypatch.setattr(adapter, "_client", lambda: sdk)
    raw = adapter.generate(
        {
            "status": "fresh",
            "score": 1,
            "evidence": [{"id": "evidence-1", "text": "Stable conditions"}],
        }
    )
    assert len(requests) == 1
    assert validate_explanation(
        raw, supplied_ids={"evidence-1"}, status="fresh"
    ).human_review_required
