from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Batch, User
from app.schemas.common import Page, Pagination

T = TypeVar("T")


def flush(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError:
        raise DomainError(409, "conflict", "Record conflicts with existing data") from None


def paginate(db: Session, statement: Select[Any], page: Pagination) -> Page[Any]:
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    items = list(db.scalars(statement.limit(page.limit).offset(page.offset)))
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


def accessible_batches(user: User) -> Select[tuple[Batch]]:
    query = select(Batch)
    if user.role == "vendor":
        query = query.where(Batch.owner_id == user.id)
    return query


def require_batch(db: Session, batch_id: str, user: User, *, writable: bool = False) -> Batch:
    query = accessible_batches(user).where(Batch.id == batch_id)
    if writable:
        query = query.with_for_update()
    batch = db.scalar(query)
    if batch is None:
        raise DomainError(404, "not_found", "Batch not found")
    if writable and batch.archived:
        raise DomainError(409, "batch_archived", "Archived batches are read-only")
    return batch
