"""Periodic deterministic assessments; AI runs in the separate explanation worker."""

import argparse
import logging
import time

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.errors import DomainError
from app.db.models import Batch, Device, User
from app.db.session import build_engine, session_factory
from app.services.assessments import assess

logger = logging.getLogger("harvest.monitor")


def run_once(factory: sessionmaker[Session], settings: Settings, actor_user_id: str) -> int:
    with factory() as db:
        actor = db.scalar(
            select(User).where(User.user_id == actor_user_id, User.active, User.role == "admin")
        )
        if actor is None:
            raise DomainError(403, "forbidden", "An active administrator must authorize the runner")
        actor_id = actor.id
        batch_ids = list(
            db.scalars(
                select(Batch.id)
                .where(
                    Batch.archived.is_(False),
                    exists(select(Device.id).where(Device.batch_id == Batch.id, Device.active)),
                )
                .order_by(Batch.id)
            )
        )
    completed = 0
    for batch_id in batch_ids:
        try:
            with factory.begin() as db:
                actor = db.get(User, actor_id)
                if actor is None or not actor.active or actor.role != "admin":
                    raise DomainError(403, "forbidden", "Runner authorization was revoked")
                assess(db, batch_id, actor, settings)
            completed += 1
        except DomainError:
            logger.warning("assessment_skipped batch_id=%s", batch_id)
    return completed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--actor-user-id",
        required=True,
        help="Existing active administrator; recorded as assessment actor",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.interval_seconds < 30:
        parser.error("Interval must be at least 30 seconds")
    settings = Settings()  # type: ignore[call-arg]
    engine = build_engine(settings)
    logging.basicConfig(level=logging.INFO)
    try:
        while True:
            count = run_once(session_factory(engine), settings, args.actor_user_id)
            logger.info("assessment_cycle completed=%s", count)
            if args.once:
                break
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        pass
    except DomainError as exc:
        parser.exit(1, f"{exc.message}\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
