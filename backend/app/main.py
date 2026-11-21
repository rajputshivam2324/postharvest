import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.api.auth import router as auth_router
from app.api.auth import users as users_router
from app.api.chat import router as chat_router
from app.api.demo import router as demo_router
from app.api.evidence import router as evidence_router
from app.api.ingestion import router as ingestion_router
from app.api.operations import router as operations_router
from app.api.pairing import router as pairing_router
from app.api.resources import router as resources_router
from app.core.config import Settings
from app.core.errors import DomainError
from app.core.rate_limit import LoginLimiter
from app.db.session import build_engine, session_factory

logger = logging.getLogger("harvest.api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()  # type: ignore[call-arg]
    engine = build_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(
        title="Post-Harvest Monitoring API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.environment == "production" else "/docs",
        openapi_url=None if settings.environment == "production" else "/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory(engine)
    app.state.login_limiter = LoginLimiter(
        settings.login_rate_limit, settings.login_rate_window_seconds
    )
    app.state.signup_limiter = LoginLimiter(
        settings.login_rate_limit, settings.login_rate_window_seconds, action="signup"
    )
    app.state.pairing_limiter = LoginLimiter(
        settings.pairing_rate_limit, settings.pairing_rate_window_seconds, action="pairing"
    )
    app.state.chat_limiter = LoginLimiter(
        settings.chat_rate_limit, settings.chat_rate_window_seconds, action="chat"
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Device-Token"],
    )

    @app.middleware("http")
    async def request_log(request: Request, call_next):  # type: ignore[no-untyped-def]
        request.state.request_id = str(uuid4())
        start = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        # Log route templates rather than paths, bodies, credentials, or query strings.
        route = request.scope.get("route")
        logger.info(
            '{"event":"request","request_id":"%s","method":"%s",'
            '"route":"%s","status":%d,"duration_ms":%.1f}',
            request.state.request_id,
            request.method,
            getattr(route, "path", "unmatched"),
            response.status_code,
            (time.monotonic() - start) * 1000,
        )
        return response

    def error(request: Request, status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": getattr(request.state, "request_id", None),
                }
            },
            headers={"WWW-Authenticate": "Bearer"} if status == 401 else None,
        )

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError) -> JSONResponse:
        return error(request, exc.status_code, exc.code, exc.message)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        return error(request, exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's input field can contain passwords/tokens, so never echo it.
        return error(request, 422, "validation_error", "Request fields failed validation")

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("database_error request_id=%s", request.state.request_id)
        return error(request, 503, "database_unavailable", "Database operation unavailable")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unexpected_error request_id=%s", request.state.request_id)
        return error(request, 500, "internal_error", "Internal server error")

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    def ready(request: Request) -> JSONResponse:
        try:
            with request.app.state.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
                # Connectivity alone is not enough: the schema must be current.
                revision = connection.execute(text("SELECT version_num FROM alembic_version"))
                if revision.scalar_one_or_none() != "0006":
                    return error(request, 503, "schema_not_ready", "Database migrations required")
        except SQLAlchemyError:
            return error(request, 503, "not_ready", "Database is not ready")
        return JSONResponse({"status": "ready"})

    app.include_router(auth_router)
    app.include_router(users_router)
    app.include_router(resources_router)
    app.include_router(ingestion_router)
    app.include_router(operations_router)
    app.include_router(evidence_router)
    app.include_router(demo_router)
    app.include_router(chat_router)
    app.include_router(pairing_router)
    return app
