from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import administrator, current_user
from app.core.config import Settings
from app.core.errors import DomainError
from app.db.models import DecisionLog, User
from app.db.session import get_db, get_settings
from app.repositories.common import flush, paginate
from app.schemas.auth import LoginInput, LoginOut, SignupInput, UserCreate, UserOut, UserUpdate
from app.schemas.common import Page, Pagination
from app.services import auth

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
users = APIRouter(prefix="/api/v1/users", tags=["users"], dependencies=[Depends(administrator)])


@router.post("/login", response_model=LoginOut)
def login(
    payload: LoginInput,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoginOut:
    request.app.state.login_limiter.check(request.client.host if request.client else "unknown")
    return auth.login(db, payload, settings)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(payload: SignupInput, request: Request, db: Session = Depends(get_db)) -> User:
    request.app.state.signup_limiter.check(request.client.host if request.client else "unknown")
    return auth.create_user(db, UserCreate(**payload.model_dump()), self_signup=True)


@users.post("", response_model=UserOut, status_code=201)
def create_user(
    payload: UserCreate, db: Session = Depends(get_db), actor: User = Depends(administrator)
) -> User:
    return auth.create_user(db, payload, actor)


@users.get("", response_model=Page[UserOut])
def list_users(page: Pagination = Depends(), db: Session = Depends(get_db)) -> Page:
    return paginate(db, select(User).order_by(User.created_at, User.id), page)


@users.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: str,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(administrator),
) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise DomainError(404, "not_found", "User not found")
    if user.id == actor.id and not payload.active:
        raise DomainError(409, "self_disable", "Cannot disable your own administrator account")
    user.active = payload.active
    db.add(
        DecisionLog(
            actor_id=actor.id,
            decision_type="user_updated",
            input_references={"user_id": user.id},
            rationale="Active flag updated",
        )
    )
    flush(db)
    return user
