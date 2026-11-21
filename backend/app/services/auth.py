from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import DomainError
from app.core.security import dummy_hash, hash_password, issue_token, verify_password
from app.db.models import DecisionLog, User
from app.repositories.common import flush
from app.schemas.auth import LoginInput, LoginOut, UserCreate, UserOut


def login(db: Session, payload: LoginInput, settings: Settings) -> LoginOut:
    user = db.scalar(select(User).where(User.user_id == payload.user_id))
    valid = verify_password(
        payload.password.get_secret_value(), user.password_hash if user else dummy_hash
    )
    if user is None or not valid or not user.active:
        raise DomainError(401, "invalid_credentials", "Invalid credentials")
    return LoginOut(
        **issue_token(user.id, settings).model_dump(), user=UserOut.model_validate(user)
    )


def create_user(
    db: Session, payload: UserCreate, actor: User | None = None, *, self_signup: bool = False
) -> User:
    user = User(
        user_id=payload.user_id,
        role=payload.role,
        password_hash=hash_password(payload.password.get_secret_value()),
    )
    db.add(user)
    flush(db)
    db.add(
        DecisionLog(
            actor_id=actor.id if actor else user.id,
            decision_type="user_created",
            input_references={"user_id": user.id},
            rationale="Public self-registration" if self_signup else "Explicit user provisioning",
        )
    )
    flush(db)
    return user
