import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import DomainError
from app.db.models import User
from app.db.session import get_db, get_settings

bearer = HTTPBearer(auto_error=False)


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None:
        raise DomainError(401, "unauthorized", "Valid Bearer authentication required")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience="harvest-api",
            issuer="harvest-monitor",
            options={"require": ["sub", "exp", "iat", "nbf", "jti", "iss", "aud"]},
        )
        if not isinstance(payload["sub"], str) or not isinstance(payload["jti"], str):
            raise jwt.InvalidTokenError()
    except jwt.InvalidTokenError:
        raise DomainError(401, "unauthorized", "Valid Bearer authentication required") from None
    user = db.get(User, payload["sub"])
    if user is None or not user.active:
        raise DomainError(401, "unauthorized", "Valid Bearer authentication required")
    return user


def operator(user: User = Depends(current_user)) -> User:
    if user.role not in {"admin", "operator"}:
        raise DomainError(403, "forbidden", "Operator role required")
    return user


def administrator(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise DomainError(403, "forbidden", "Administrator role required")
    return user
