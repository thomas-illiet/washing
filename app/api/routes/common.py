"""Shared helpers used by multiple API route modules."""

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams
from internal.contracts.http.resources import ApiModel, PaginatedResponse

ModelT = TypeVar("ModelT")
ResourceT = TypeVar("ResourceT", bound=ApiModel)


def get_or_404(db: Session, model: type[ModelT], object_id: int, detail: str) -> ModelT:
    """Return a database row or raise a 404 HTTP error."""
    db_object = db.get(model, object_id)
    if db_object is None:
        raise HTTPException(status_code=404, detail=detail)
    return db_object


def apply_patch(db_object: Any, values: dict[str, Any]) -> None:
    """Apply a partial update payload to an ORM instance."""
    for field, value in values.items():
        setattr(db_object, field, value)


def commit_or_409(db: Session, detail: str) -> None:
    """Commit the transaction or map integrity errors to HTTP 409."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc


def paginate_query(
    query: Any,
    resource_model: type[ResourceT],
    pagination: PaginationParams,
    *order_by: Any,
    transform: Callable[[Any], ResourceT] | None = None,
) -> PaginatedResponse[ResourceT]:
    """Paginate a SQLAlchemy query with a stable ordering and serialized items."""
    total = query.order_by(None).count()
    ordered_query = query.order_by(*order_by) if order_by else query
    rows = ordered_query.offset(pagination.offset).limit(pagination.limit).all()
    serialize = transform or resource_model.model_validate
    return PaginatedResponse(
        items=[serialize(row) for row in rows],
        offset=pagination.offset,
        limit=pagination.limit,
        total=total,
    )
