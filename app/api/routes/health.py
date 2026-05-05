"""Simple healthcheck route."""

from fastapi import APIRouter


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return a lightweight liveness payload."""
    return {"status": "ok"}
