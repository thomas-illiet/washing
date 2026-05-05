"""Platform CRUD routes."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404
from internal.contracts.http.resources import PlatformCreate, PlatformRead, PlatformUpdate
from internal.infra.db.models import Platform


router = APIRouter(prefix="/platforms", tags=["platforms"])


@router.post("", response_model=PlatformRead, status_code=status.HTTP_201_CREATED)
def create_platform(payload: PlatformCreate, db: Session = Depends(get_db)) -> Platform:
    """Create a platform entry."""
    platform = Platform(**payload.model_dump())
    db.add(platform)
    commit_or_409(db, "platform name already exists")
    db.refresh(platform)
    return platform


@router.get("", response_model=list[PlatformRead])
def list_platforms(offset: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> list[Platform]:
    """List platforms with basic pagination."""
    return db.query(Platform).offset(offset).limit(limit).all()


@router.get("/{platform_id}", response_model=PlatformRead)
def get_platform(platform_id: int, db: Session = Depends(get_db)) -> Platform:
    """Return one platform by id."""
    return get_or_404(db, Platform, platform_id, "platform not found")


@router.patch("/{platform_id}", response_model=PlatformRead)
def update_platform(platform_id: int, payload: PlatformUpdate, db: Session = Depends(get_db)) -> Platform:
    """Patch an existing platform."""
    platform = get_or_404(db, Platform, platform_id, "platform not found")
    apply_patch(platform, payload.model_dump(exclude_unset=True))
    commit_or_409(db, "platform name already exists")
    db.refresh(platform)
    return platform


@router.delete("/{platform_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_platform(platform_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a platform."""
    platform = get_or_404(db, Platform, platform_id, "platform not found")
    db.delete(platform)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
