import time
from collections.abc import Generator

from fastapi import Request
from sqlalchemy import Engine, create_engine, event, exc
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import Pool, StaticPool

from app.core.config import Settings


def build_engine(settings: Settings) -> Engine:
    if settings.sqlalchemy_url.startswith("sqlite"):
        return create_engine(
            settings.sqlalchemy_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    engine = create_engine(
        settings.sqlalchemy_url,
        pool_size=settings.database_pool_size,
        max_overflow=5,
        pool_recycle=1800,
        connect_args={"connect_timeout": 5, "options": "-c timezone=UTC"},
    )
    install_idle_ping(engine)
    return engine


IDLE_PING_SECONDS = 20.0


def install_idle_ping(engine: Engine | Pool, idle_seconds: float = IDLE_PING_SECONDS) -> None:
    """Check a pooled connection only after it has sat idle.

    ``pool_pre_ping`` costs one network round trip on every checkout. On a remote
    serverless database that is a large share of each request. Connections used
    within ``idle_seconds`` are trusted; older ones are pinged, and a dead one is
    replaced transparently (the pool retries the checkout on DisconnectionError).
    """

    @event.listens_for(engine, "checkin")
    def _mark_used(dbapi_connection, connection_record) -> None:  # type: ignore[no-untyped-def]
        connection_record.info["last_used"] = time.monotonic()

    @event.listens_for(engine, "checkout")
    def _ping_if_idle(dbapi_connection, connection_record, connection_proxy) -> None:  # type: ignore[no-untyped-def]
        last_used = connection_record.info.get("last_used")
        if last_used is not None and time.monotonic() - last_used < idle_seconds:
            return
        try:
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("SELECT 1")
            finally:
                cursor.close()
            dbapi_connection.rollback()
        except Exception as error:  # a broken connection raises driver-specific errors
            raise exc.DisconnectionError("connection failed its idle check") from error


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session]:
    with request.app.state.session_factory() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_settings(request: Request) -> Settings:
    return request.app.state.settings
