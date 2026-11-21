"""Create a persistent synthetic batch and optionally explain just its assessment."""

import argparse
import json

from sqlalchemy import func, select

from app.core.config import Settings
from app.db.models import Batch, RiskAssessment, SensorReading, User
from app.db.session import build_engine, session_factory
from app.repositories.common import require_batch
from app.services.assessments import assess
from app.services.demo import seed_demo
from app.worker import process_one


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--user-id",
        help="Existing operator/admin; otherwise use the oldest active administrator",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Process only this assessment with the configured real AI adapter",
    )
    parser.add_argument(
        "--batch-id", help="Reassess an existing seeded demo; retain earlier assessments"
    )
    args = parser.parse_args()
    settings = Settings()  # type: ignore[call-arg]
    engine = build_engine(settings)
    factory = session_factory(engine)
    try:
        with factory.begin() as db:
            users = select(User).where(User.active.is_(True))
            users = (
                users.where(User.user_id == args.user_id)
                if args.user_id
                else users.where(User.role == "admin")
            )
            actor = db.scalar(users.order_by(User.created_at, User.id).limit(1))
            if actor is None:
                parser.error(
                    "No eligible account. Supply --user-id for an active operator or administrator."
                )
            if args.batch_id:
                existing = require_batch(db, args.batch_id, actor, writable=True)
                if not existing.attributes.get("seeded_demo"):
                    parser.error("--batch-id must reference a seeded demo batch")
                assessment = assess(db, existing.id, actor, settings)
                count = (
                    db.scalar(
                        select(func.count())
                        .select_from(SensorReading)
                        .where(SensorReading.batch_id == existing.id)
                    )
                    or 0
                )
            else:
                assessment, count = seed_demo(db, actor, settings)
            assessment_id, batch_id = assessment.id, assessment.batch_id
            batch = db.get(Batch, batch_id)
            print(
                json.dumps(
                    {
                        "identifier": batch.identifier if batch else None,
                        "batch_id": batch_id,
                        "readings": count,
                        "simulated": True,
                        "status": assessment.status,
                        "ai_job_status": assessment.ai_job_status,
                    }
                ),
                flush=True,
            )
        if args.explain:
            process_one(factory, settings, assessment_id=assessment_id)
        with factory() as db:
            stored = db.get(RiskAssessment, assessment_id)
            if stored:
                print(
                    json.dumps(
                        {
                            "assessment_id": stored.id,
                            "ai_status": stored.ai_status,
                            "ai_job_status": stored.ai_job_status,
                            "evidence_citations": len(stored.cited_evidence_ids),
                            "output_available": stored.ai_explanation is not None,
                        }
                    ),
                    flush=True,
                )
    except Exception as exc:
        # Provider/database exceptions can contain credentials; emit only the type.
        parser.exit(1, f"Demo operation failed ({type(exc).__name__}).\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
