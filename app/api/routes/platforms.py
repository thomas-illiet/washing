"""Platform CRUD routes."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404, paginate_query
from internal.contracts.http.resources import PaginatedResponse, PlatformCreate, PlatformRead, PlatformUpdate
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


@router.get("", response_model=PaginatedResponse[PlatformRead])
def list_platforms(
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[PlatformRead]:
    """List platforms with stable offset pagination."""
    query = db.query(Platform)
    return paginate_query(query, PlatformRead, pagination, Platform.name.asc(), Platform.id.asc())


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
