"""Platform CRUD routes."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404, paginate_query
from internal.contracts.http.resources import (
    PaginatedResponse,
    PlatformCreate,
    PlatformRead,
    PlatformSummaryRead,
    PlatformUpdate,
)
from internal.infra.db.models import Machine, MachineOptimization, MachineProvider, MachineProvisioner, Platform


router = APIRouter(prefix="/platforms", tags=["Platforms"])


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


@router.get("/{platform_id}/summary", response_model=PlatformSummaryRead)
def get_platform_summary(platform_id: int, db: Session = Depends(get_db)) -> PlatformSummaryRead:
    """Return aggregate inventory, connector, and optimization counts for one platform."""
    get_or_404(db, Platform, platform_id, "platform not found")

    machines = (
        db.query(func.count(Machine.id))
        .filter(Machine.platform_id == platform_id)
        .scalar()
        or 0
    )
    application_keys = (
        db.query(Machine.application, Machine.environment, Machine.region)
        .filter(Machine.platform_id == platform_id)
        .filter(Machine.application.is_not(None))
        .group_by(Machine.application, Machine.environment, Machine.region)
        .all()
    )
    applications = len(application_keys)
    providers = (
        db.query(func.count(MachineProvider.id))
        .filter(MachineProvider.platform_id == platform_id)
        .scalar()
        or 0
    )
    enabled_providers = (
        db.query(func.count(MachineProvider.id))
        .filter(MachineProvider.platform_id == platform_id)
        .filter(MachineProvider.enabled.is_(True))
        .scalar()
        or 0
    )
    provisioners = (
        db.query(func.count(MachineProvisioner.id))
        .filter(MachineProvisioner.platform_id == platform_id)
        .scalar()
        or 0
    )
    enabled_provisioners = (
        db.query(func.count(MachineProvisioner.id))
        .filter(MachineProvisioner.platform_id == platform_id)
        .filter(MachineProvisioner.enabled.is_(True))
        .scalar()
        or 0
    )
    optimization_query = (
        db.query(MachineOptimization)
        .join(Machine, MachineOptimization.machine_id == Machine.id)
        .filter(Machine.platform_id == platform_id)
        .filter(MachineOptimization.is_current.is_(True))
    )
    current_optimizations = optimization_query.count()
    optimizations_by_status = {
        status: count
        for status, count in (
            db.query(MachineOptimization.status, func.count(MachineOptimization.id))
            .join(Machine, MachineOptimization.machine_id == Machine.id)
            .filter(Machine.platform_id == platform_id)
            .filter(MachineOptimization.is_current.is_(True))
            .group_by(MachineOptimization.status)
            .all()
        )
    }
    optimizations_by_action = {
        action: count
        for action, count in (
            db.query(MachineOptimization.action, func.count(MachineOptimization.id))
            .join(Machine, MachineOptimization.machine_id == Machine.id)
            .filter(Machine.platform_id == platform_id)
            .filter(MachineOptimization.is_current.is_(True))
            .group_by(MachineOptimization.action)
            .all()
        )
    }
    return PlatformSummaryRead(
        platform_id=platform_id,
        machines=machines,
        applications=applications,
        providers=providers,
        enabled_providers=enabled_providers,
        provisioners=provisioners,
        enabled_provisioners=enabled_provisioners,
        current_optimizations=current_optimizations,
        current_optimizations_by_status=optimizations_by_status,
        current_optimizations_by_action=optimizations_by_action,
    )


@router.patch("/{platform_id}", response_model=PlatformRead)
def update_platform(platform_id: int, payload: PlatformUpdate, db: Session = Depends(get_db)) -> Platform:
    """Patch an existing platform."""
    platform = get_or_404(db, Platform, platform_id, "platform not found")
    apply_patch(platform, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(platform)
    return platform


@router.delete("/{platform_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_platform(platform_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a platform."""
    platform = get_or_404(db, Platform, platform_id, "platform not found")
    db.delete(platform)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
