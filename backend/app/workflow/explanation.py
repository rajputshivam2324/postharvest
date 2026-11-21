from collections.abc import Callable
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.ai.gemini import AIDisabled, GeminiAdapter
from app.ai.schema import validate_explanation
from app.retrieval.query import EvidenceItem

WORKFLOW_VERSION = "fixed-graph-v1"


class State(TypedDict, total=False):
    status: str
    features: dict[str, Any]
    score: float | None
    evidence: list[EvidenceItem]
    ai_status: str
    raw: str
    output: dict[str, Any] | None
    visited: list[str]


def build_workflow(
    adapter: GeminiAdapter, retriever: Callable[[], list[EvidenceItem]]
) -> CompiledStateGraph:
    """Fixed edges, including deterministic terminal quality/disabled paths. Returns only data."""

    def load_features(state: State) -> dict:
        return {"visited": ["load_features"], "output": None}

    def quality_gate(state: State) -> dict:
        return {
            "visited": state["visited"] + ["quality_gate"],
            "ai_status": "disabled" if state["score"] is None or not adapter.enabled else "ok",
        }

    def route_quality(state: State) -> str:
        return "fallback" if state["ai_status"] == "disabled" else "retrieve_evidence"

    def retrieve_evidence(state: State) -> dict:
        try:
            evidence = retriever()
            status = "ok" if evidence else "failed"
        except Exception:
            evidence, status = [], "failed"
        return {
            "evidence": evidence,
            "ai_status": status,
            "visited": state["visited"] + ["retrieve_evidence"],
        }

    def explain(state: State) -> dict:
        result = {"visited": state["visited"] + ["explain"]}
        if state["ai_status"] != "ok":
            return result
        try:
            raw = adapter.generate(
                {
                    "status": state["status"],
                    "score": state["score"],
                    "features": state["features"],
                    "evidence": [e.model_dump() for e in state["evidence"]],
                }
            )
            return {**result, "raw": raw}
        except AIDisabled:
            return {**result, "ai_status": "disabled"}
        except Exception:
            return {**result, "ai_status": "failed"}

    def validate(state: State) -> dict:
        result = {"visited": state["visited"] + ["validate"]}
        if state["ai_status"] != "ok":
            return result
        try:
            output = validate_explanation(
                state["raw"], supplied_ids={e.id for e in state["evidence"]}, status=state["status"]
            )
            return {**result, "output": output.model_dump()}
        except (ValueError, TypeError):
            return {**result, "ai_status": "invalid_output"}

    def fallback(state: State) -> dict:
        return {
            "output": state.get("output") if state["ai_status"] == "ok" else None,
            "visited": state["visited"] + ["fallback"],
        }

    graph = StateGraph(State)
    for name, node in [
        ("load_features", load_features),
        ("quality_gate", quality_gate),
        ("retrieve_evidence", retrieve_evidence),
        ("explain", explain),
        ("validate", validate),
        ("fallback", fallback),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "load_features")
    graph.add_edge("load_features", "quality_gate")
    graph.add_conditional_edges(
        "quality_gate",
        route_quality,
        {"fallback": "fallback", "retrieve_evidence": "retrieve_evidence"},
    )
    graph.add_edge("retrieve_evidence", "explain")
    graph.add_edge("explain", "validate")
    graph.add_edge("validate", "fallback")
    graph.add_edge("fallback", END)
    return graph.compile()
