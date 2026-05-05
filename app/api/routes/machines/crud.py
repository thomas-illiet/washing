"""Machine CRUD and flavor history routes."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404, paginate_query
from internal.contracts.http.resources import (
    MachineCreate,
    MachineFlavorHistoryRead,
    MachineRead,
    MachineUpdate,
    PaginatedResponse,
)
from internal.infra.db.models import Machine, MachineFlavorHistory


router = APIRouter(prefix="/machines", tags=["machines"])


@router.post("", response_model=MachineRead, status_code=status.HTTP_201_CREATED)
def create_machine(payload: MachineCreate, db: Session = Depends(get_db)) -> Machine:
    """Create a machine row."""
    machine = Machine(**payload.model_dump())
    db.add(machine)
    commit_or_409(db, "machine already exists for this platform or provisioner external id")
    db.refresh(machine)
    return machine


@router.get("", response_model=PaginatedResponse[MachineRead])
def list_machines(
    platform_id: int | None = None,
    application_id: int | None = None,
    source_provisioner_id: int | None = None,
    environment: str | None = None,
    region: str | None = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineRead]:
    """List machines with optional platform and ownership filters."""
    query = db.query(Machine)
    if platform_id is not None:
        query = query.filter(Machine.platform_id == platform_id)
    if application_id is not None:
        query = query.filter(Machine.application_id == application_id)
    if source_provisioner_id is not None:
        query = query.filter(Machine.source_provisioner_id == source_provisioner_id)
    if environment is not None:
        query = query.filter(Machine.environment == environment)
    if region is not None:
        query = query.filter(Machine.region == region)
    return paginate_query(query, MachineRead, pagination, Machine.hostname.asc(), Machine.id.asc())


@router.get("/{machine_id:int}", response_model=MachineRead)
def get_machine(machine_id: int, db: Session = Depends(get_db)) -> Machine:
    """Return one machine by id."""
    return get_or_404(db, Machine, machine_id, "machine not found")


@router.patch("/{machine_id:int}", response_model=MachineRead)
def update_machine(machine_id: int, payload: MachineUpdate, db: Session = Depends(get_db)) -> Machine:
    """Patch a machine."""
    machine = get_or_404(db, Machine, machine_id, "machine not found")
    apply_patch(machine, payload.model_dump(exclude_unset=True))
    commit_or_409(db, "machine already exists for this platform or provisioner external id")
    db.refresh(machine)
    return machine


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
