"""Shared FastAPI dependencies."""

from fastapi import Query

from internal.infra.db.session import get_db


class PaginationParams:
    """Shared offset/limit pagination parameters for list endpoints."""

    def __init__(
        self,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1),
    ) -> None:
        self.offset = offset
        self.limit = limit


__all__ = ["PaginationParams", "get_db"]
