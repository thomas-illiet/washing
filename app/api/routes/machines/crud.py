"""Machine read/delete and flavor history routes."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import get_or_404, paginate_query
from internal.domain import normalize_application_code, normalize_dimension
from internal.contracts.http.resources import (
    MachineFlavorHistoryRead,
    MachineRead,
    PaginatedResponse,
)
from internal.infra.db.models import Machine, MachineFlavorHistory


router = APIRouter(prefix="/machines", tags=["Machines"])


@router.get("", response_model=PaginatedResponse[MachineRead])
def list_machines(
    platform_id: int | None = None,
    application: str | None = None,
    source_provisioner_id: int | None = None,
    environment: str | None = None,
    region: str | None = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineRead]:
    """List machines with optional platform and ownership filters."""
    query = db.query(Machine)
    normalized_application = normalize_application_code(application)
    normalized_environment = normalize_dimension(environment)
    normalized_region = normalize_dimension(region)
    if platform_id is not None:
        query = query.filter(Machine.platform_id == platform_id)
    if normalized_application is not None:
        query = query.filter(Machine.application == normalized_application)
    if source_provisioner_id is not None:
        query = query.filter(Machine.source_provisioner_id == source_provisioner_id)
    if normalized_environment is not None:
        query = query.filter(Machine.environment == normalized_environment)
    if normalized_region is not None:
        query = query.filter(Machine.region == normalized_region)
    return paginate_query(query, MachineRead, pagination, Machine.hostname.asc(), Machine.id.asc())


@router.get("/{machine_id:int}", response_model=MachineRead)
def get_machine(machine_id: int, db: Session = Depends(get_db)) -> Machine:
    """Return one machine by id."""
    return get_or_404(db, Machine, machine_id, "machine not found")


@router.delete("/{machine_id:int}", status_code=status.HTTP_204_NO_CONTENT)
def delete_machine(machine_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a machine."""
    machine = get_or_404(db, Machine, machine_id, "machine not found")
    db.delete(machine)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{machine_id:int}/flavor-history", response_model=PaginatedResponse[MachineFlavorHistoryRead])
def list_machine_flavor_history(
    machine_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineFlavorHistoryRead]:
    """List flavor change history for one machine."""
    get_or_404(db, Machine, machine_id, "machine not found")
    query = (
        db.query(MachineFlavorHistory)
        .filter(MachineFlavorHistory.machine_id == machine_id)
    )
    return paginate_query(
        query,
        MachineFlavorHistoryRead,
        pagination,
        MachineFlavorHistory.changed_at.desc(),
        MachineFlavorHistory.id.desc(),
    )
