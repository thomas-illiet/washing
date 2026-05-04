from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


ModelT = TypeVar("ModelT")


def get_or_404(db: Session, model: type[ModelT], object_id: int, detail: str) -> ModelT:
    db_object = db.get(model, object_id)
    if db_object is None:
        raise HTTPException(status_code=404, detail=detail)
    return db_object


def apply_patch(db_object: Any, values: dict[str, Any]) -> None:
    for field, value in values.items():
        setattr(db_object, field, value)


def commit_or_409(db: Session, detail: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=detail) from exc
