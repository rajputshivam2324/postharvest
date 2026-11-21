"""Live Neon/Gemini verification with synthetic data inside a rolled-back PostgreSQL schema."""

import argparse
import json
import logging
import math
import secrets
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.ai.gemini import GeminiAdapter
from app.ai.schema import validate_explanation
from app.core.config import Settings
from app.core.time import utcnow
from app.db.models import EvidenceChunk
from app.db.session import build_engine
from app.main import create_app
from app.risk.policy import RiskPolicy
from app.schemas.auth import UserCreate
from app.services.auth import create_user
from app.worker import process_one


def failure(exc: Exception) -> dict[str, Any]:
    """Return diagnostic categories only; provider/driver errors can include credentials/URLs."""
    original = getattr(exc, "orig", exc)
    message = str(original).lower()
    category = "operation_failed"
    if any(word in message for word in ("resolve", "name resolution", "name or service")):
        category = "dns_unavailable"
    elif any(word in message for word in ("connection", "network", "connect", "unreachable")):
        category = "connection_unavailable"
    elif getattr(exc, "code", None) in {401, 403}:
        category = "authentication_or_permission"
    elif getattr(exc, "code", None) == 429:
        category = "provider_rate_limit"
    code = getattr(exc, "code", None)
    return {
        "status": "failed",
        "category": category,
        "error_type": type(original).__name__,
        "status_code": code if isinstance(code, int) else None,
    }


def expect(response: Any, code: int) -> dict[str, Any]:
    if response.status_code != code:
        raise ValueError(f"Unexpected HTTP status {response.status_code}; expected {code}")
    return response.json()


def database_flow(engine: Engine, settings: Settings) -> dict[str, Any]:
    # Simulator is deliberately a sibling of backend, rather than an app dependency.
    repository_root = str(Path(__file__).resolve().parents[2])
    if repository_root not in sys.path:
        sys.path.append(repository_root)
    from simulator.scenarios import generate

    schema = "harvest_smoke_" + uuid4().hex
    result: dict[str, Any] = {}
    # PostgreSQL DDL and data stay in this outer transaction. Sessions release only savepoints.
    # The version table is explicitly scoped, so a public installation cannot be mistaken for it.
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            result["connectivity"] = {
                "status": "ok",
                "select_1": connection.scalar(text("SELECT 1")),
                "postgres_version": connection.scalar(text("SHOW server_version")),
            }
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            config.attributes["version_table_schema"] = schema
            command.upgrade(config, "head")
            revision = connection.scalar(
                text(f'SELECT version_num FROM "{schema}".alembic_version')
            )
            if revision != "0004":
                raise ValueError("Migrations did not reach 0004")
            extension = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname='vector'")
            )
            result["migrations_pgvector"] = {
                "status": "ok",
                "revision": revision,
                "extension_version": extension,
            }
            factory = sessionmaker(
                bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
            password = secrets.token_urlsafe(24)
            user_id = "smoke-" + uuid4().hex
            with factory.begin() as db:
                create_user(
                    db, UserCreate(user_id=user_id, password=SecretStr(password), role="admin")
                )
            # Short test window changes only this process's settings, never the local .env.
            test_settings = settings.model_copy(
                update={
                    "risk_policy": RiskPolicy(
                        version="live-smoke-v1", window_seconds=3600, min_samples=6
                    )
                }
            )
            app = create_app(test_settings)
            app.state.session_factory = factory
            with TestClient(app) as client:
                token = expect(
                    client.post(
                        "/api/v1/auth/login", json={"user_id": user_id, "password": password}
                    ),
                    200,
                )["access_token"]
                auth = {"Authorization": f"Bearer {token}"}
                expect(client.get("/api/v1/auth/me", headers=auth), 200)
                if client.get("/api/v1/batches").status_code != 401:
                    raise ValueError("Anonymous access was not rejected")
                result["authentication"] = {"status": "ok"}
                batch = expect(
                    client.post(
                        "/api/v1/batches",
                        headers=auth,
                        json={
                            "identifier": "live-smoke-" + uuid4().hex,
                            "commodity": "tomato",
                            "quantity": 1,
                            "unit": "kg",
                            "storage_location": "isolated smoke test",
                            "attributes": {"synthetic_test": True},
                        },
                    ),
                    201,
                )
                device = expect(
                    client.post(
                        "/api/v1/devices",
                        headers=auth,
                        json={
                            "identifier": "simulator-" + uuid4().hex,
                            "batch_id": batch["id"],
                            "simulated": True,
                        },
                    ),
                    201,
                )
                now = utcnow()
                expect(
                    client.post(
                        f"/api/v1/devices/{device['id']}/baseline",
                        headers=auth,
                        json={
                            "gas_adc": 1000,
                            "recorded_at": (now - timedelta(hours=2)).isoformat(),
                        },
                    ),
                    201,
                )
                expect(
                    client.post(
                        f"/api/v1/batches/{batch['id']}/observations",
                        headers=auth,
                        json={
                            "observed_at": now.isoformat(),
                            "condition": "Synthetic test: firm tomatoes",
                            "visible_mould": False,
                        },
                    ),
                    201,
                )
                rows = generate(
                    scenario="deterioration",
                    seed=42,
                    start=now - timedelta(hours=1),
                    count=13,
                    interval_seconds=300,
                    device_id=device["id"],
                    batch_id=batch["id"],
                    run_id=uuid4().hex,
                )
                device_auth = {"X-Device-Token": device["credential"]}
                for row in rows:
                    expect(client.post("/api/v1/readings", headers=device_auth, json=row), 201)
                duplicate = expect(
                    client.post("/api/v1/readings", headers=device_auth, json=rows[-1]), 200
                )
                if not duplicate["duplicate"]:
                    raise ValueError("Retry was not recognized")
                history = expect(
                    client.get(f"/api/v1/batches/{batch['id']}/readings", headers=auth), 200
                )
                if history["total"] != len(rows):
                    raise ValueError("Reading count does not match")
                result["ingestion_history_idempotency"] = {
                    "status": "ok",
                    "reading_count": len(rows),
                }
                assessment = expect(
                    client.post(f"/api/v1/batches/{batch['id']}/assessments", headers=auth), 201
                )
                if assessment["status"] != "spoiling" or assessment["score"] is None:
                    raise ValueError(
                        "Synthetic risk assessment did not match the configured policy"
                    )
                result["deterministic_risk"] = {
                    "status": "ok",
                    "risk_status": assessment["status"],
                    "score": assessment["score"],
                }
                if not process_one(factory, test_settings):
                    raise ValueError("No explanation job was queued")
                updated = expect(
                    client.get(f"/api/v1/batches/{batch['id']}/assessment", headers=auth), 200
                )
                if (
                    updated["explanation"] != assessment["explanation"]
                    or updated["status"] != assessment["status"]
                ):
                    raise ValueError("AI changed the deterministic assessment")
                result["ai_workflow"] = {
                    "status": "ok" if updated["ai_status"] == "ok" else "failed",
                    "ai_status": updated["ai_status"],
                    "citations": len(updated["cited_evidence_ids"]),
                }
                with factory() as db:
                    count = db.scalar(
                        select(func.count())
                        .select_from(EvidenceChunk)
                        .where(EvidenceChunk.embedding.is_not(None))
                    )
                    # Execute actual PostgreSQL vector distance, not a SQLite fallback.
                    distance = db.scalar(
                        select(EvidenceChunk.embedding.cosine_distance([1.0] + [0.0] * 767))
                        .where(EvidenceChunk.embedding.is_not(None))
                        .limit(1)
                    )
                result["vector_search"] = {
                    "status": "ok" if count and distance is not None else "failed",
                    "embedded_chunks": count,
                }
                evidence = expect(
                    client.get(f"/api/v1/batches/{batch['id']}/evidence", headers=auth), 200
                )
                result["retrieval"] = {
                    "status": "ok" if evidence else "failed",
                    "items": len(evidence),
                }
                priorities = expect(client.get("/api/v1/priorities", headers=auth), 200)
                alerts = expect(client.get("/api/v1/alerts", headers=auth), 200)
                if priorities["total"] != 1 or alerts["total"] != 1:
                    raise ValueError("Priorities or alerts were not recorded")
                expect(
                    client.post(
                        f"/api/v1/alerts/{alerts['items'][0]['id']}/acknowledge", headers=auth
                    ),
                    200,
                )
                decisions = expect(
                    client.get(f"/api/v1/batches/{batch['id']}/decisions", headers=auth), 200
                )
                result["priorities_alerts_audit"] = {
                    "status": "ok",
                    "audit_records": decisions["total"],
                    "notification_status": alerts["items"][0]["delivery_status"],
                }
        except Exception as exc:
            result["database_flow"] = failure(exc)
        finally:
            transaction.rollback()
            result["cleanup"] = {"status": "ok", "test_schema_and_rows": "rolled_back"}
    return result


def run(settings: Settings) -> dict[str, Any]:
    result: dict[str, Any] = {"checks": {}, "test_data": "synthetic only"}
    engine = build_engine(settings)
    try:
        try:
            result["checks"].update(database_flow(engine, settings))
        except Exception as exc:
            result["checks"]["neon_connectivity"] = failure(exc)
    finally:
        engine.dispose()
    adapter = GeminiAdapter(settings)
    try:
        embedding = adapter.embed("Synthetic monitoring test: stable tomato conditions.")
        norm = math.sqrt(sum(value * value for value in embedding))
        result["checks"]["gemini_embedding"] = {
            "status": "ok",
            "dimensions": len(embedding),
            "normalized": abs(norm - 1) < 1e-6,
        }
    except Exception as exc:
        result["checks"]["gemini_embedding"] = failure(exc)
    try:
        raw = adapter.generate(
            {
                "status": "fresh",
                "score": 1,
                "features": {"synthetic": True},
                "evidence": [
                    {
                        "id": "smoke-evidence",
                        "source_type": "observation",
                        "text": "Synthetic example: stable temperature and humidity.",
                    }
                ],
            }
        )
        validated = validate_explanation(raw, supplied_ids={"smoke-evidence"}, status="fresh")
        result["checks"]["gemini_explanation"] = {
            "status": "ok",
            "validated": True,
            "human_review_required": validated.human_review_required,
        }
    except Exception as exc:
        result["checks"]["gemini_explanation"] = failure(exc)
    result["status"] = (
        "passed"
        if all(check["status"] == "ok" for check in result["checks"].values())
        else "failed"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write a credential-free JSON report")
    args = parser.parse_args()
    # Disable third-party request logs; report only fixed diagnostic fields.
    logging.disable(logging.CRITICAL)
    try:
        settings = Settings()  # type: ignore[call-arg]
        if not settings.gemini_api_key:
            raise ValueError("Gemini API key is not configured")
        report = run(settings)
    except Exception as exc:
        report = {"status": "failed", "checks": {"configuration": failure(exc)}}
    serialized = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized)
    print(serialized, end="")
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
