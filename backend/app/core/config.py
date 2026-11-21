from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.risk.policy import RiskPolicy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    environment: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    jwt_secret: SecretStr
    jwt_expiry_minutes: int = Field(default=30, ge=1, le=1440)
    cors_origins: list[str] = Field(default_factory=list)
    database_pool_size: int = Field(default=5, ge=1, le=50)
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"
    gemini_embedding_model: str = "gemini-embedding-001"
    ai_timeout_seconds: int = Field(default=20, ge=1, le=60)
    retrieval_top_k: int = Field(default=6, ge=1, le=20)
    retrieval_token_budget: int = Field(default=2000, ge=100, le=8000)
    device_stale_seconds: int = Field(default=900, ge=60)
    max_future_seconds: int = Field(default=60, ge=0, le=300)
    max_history_days: int = Field(default=30, ge=1, le=365)
    login_rate_limit: int = Field(default=20, ge=1, le=1000)
    login_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    pairing_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    pairing_rate_limit: int = Field(default=10, ge=1, le=1000)
    pairing_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    chat_rate_limit: int = Field(default=20, ge=1, le=1000)
    chat_rate_window_seconds: int = Field(default=60, ge=1, le=3600)
    chat_evidence_chars: int = Field(default=12000, ge=2000, le=40000)
    risk_policy: RiskPolicy = Field(default_factory=RiskPolicy)
    priority_risk_weight: float = Field(default=1, ge=0, le=10)
    priority_stale_bonus: float = Field(default=15, ge=0, le=100)
    priority_insufficient_bonus: float = Field(default=25, ge=0, le=100)

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def empty_key(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("jwt_secret")
    @classmethod
    def strong_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32 or "REPLACE" in value.get_secret_value():
            raise ValueError("JWT_SECRET must be a random secret of at least 32 characters")
        return value

    @model_validator(mode="after")
    def validate_database(self) -> "Settings":
        url = make_url(self.database_url.get_secret_value())
        if url.get_backend_name() != "postgresql":
            if not (self.environment == "test" and url.get_backend_name() == "sqlite"):
                raise ValueError("PostgreSQL is required outside tests")
        if self.environment == "production":
            if url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
                raise ValueError("Production database connections require TLS")
            if any("*" in origin for origin in self.cors_origins):
                raise ValueError("Production CORS must use explicit origins")
        return self

    @property
    def sqlalchemy_url(self) -> str:
        url = make_url(self.database_url.get_secret_value())
        if url.get_backend_name() == "postgresql":
            url = url.set(drivername="postgresql+psycopg")
        return url.render_as_string(hide_password=False)
