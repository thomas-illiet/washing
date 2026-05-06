"""Shared helpers for Celery worker tasks."""

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.orm import Session

from internal.infra.db.session import SessionLocal


ReturnT = TypeVar("ReturnT")


def run_with_db_session(operation: Callable[[Session], ReturnT]) -> ReturnT:
    """Execute one operation inside a short-lived database session."""
    db = SessionLocal()
    try:
        return operation(db)
    finally:
        db.close()
