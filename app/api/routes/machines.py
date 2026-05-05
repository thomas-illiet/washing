"""Machine CRUD, history, and machine metric routes."""

from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404
from internal.contracts.http.resources import (
    MachineCreate,
    MachineFlavorHistoryRead,
    MachineMetricRead,
    MachineRead,
    MachineUpdate,
    PaginatedResponse,
    Scope,
)
from internal.infra.db.models import (
    Machine,
    MachineCPUMetric,
    MachineDiskMetric,
    MachineFlavorHistory,
    MachineProvider,
    MachineProviderProvisioner,
    MachineRAMMetric,
)


router = APIRouter(prefix="/machines", tags=["machines"])

METRIC_MODELS = {
    "cpu": MachineCPUMetric,
    "ram": MachineRAMMetric,
    "disk": MachineDiskMetric,
}


def _metric_query(
    scope: Scope,
    db: Session,
    platform_id: int | None = None,
    provider_id: int | None = None,
    provisioner_id: int | None = None,
    machine_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
):
    """Build the shared machine metric query for one scope."""
    model = METRIC_MODELS[scope]
    query = db.query(model).join(MachineProvider, model.provider_id == MachineProvider.id)

    if platform_id is not None:
        query = query.filter(MachineProvider.platform_id == platform_id)
    if provider_id is not None:
        query = query.filter(model.provider_id == provider_id)
    if provisioner_id is not None:
        query = query.join(MachineProviderProvisioner, MachineProviderProvisioner.provider_id == model.provider_id)
        query = query.filter(MachineProviderProvisioner.provisioner_id == provisioner_id)
    if machine_id is not None:
        query = query.filter(model.machine_id == machine_id)
    if start is not None:
        query = query.filter(model.date >= start)
    if end is not None:
        query = query.filter(model.date <= end)

    return model, query


def _paginate_metric_query(model, query, offset: int, limit: int) -> PaginatedResponse[MachineMetricRead]:
    """Return a paginated metric response with offset metadata."""
    total = query.order_by(None).count()
    items = query.order_by(model.date.desc(), model.id.desc()).offset(offset).limit(limit).all()
    return PaginatedResponse[MachineMetricRead](
        items=[MachineMetricRead.model_validate(item) for item in items],
        offset=offset,
        limit=limit,
        total=total,
    )


@router.post("", response_model=MachineRead, status_code=status.HTTP_201_CREATED)
def create_machine(payload: MachineCreate, db: Session = Depends(get_db)) -> Machine:
    """Create a machine row."""
    machine = Machine(**payload.model_dump())
    db.add(machine)
    commit_or_409(db, "machine already exists for this platform or provisioner external id")
    db.refresh(machine)
    return machine


@router.get("", response_model=list[MachineRead])
def list_machines(
    platform_id: int | None = None,
    application_id: int | None = None,
    source_provisioner_id: int | None = None,
    environment: str | None = None,
    region: str | None = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[Machine]:
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
    return query.offset(offset).limit(limit).all()


@router.get("/metrics", response_model=PaginatedResponse[MachineMetricRead])
def list_machine_metrics(
    metric_type: Scope = Query(alias="type"),
    platform_id: int | None = None,
    provider_id: int | None = None,
    provisioner_id: int | None = None,
    machine_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineMetricRead]:
    """List paginated metrics for one metric type across machines."""
    model, query = _metric_query(metric_type, db, platform_id, provider_id, provisioner_id, machine_id, start, end)
    return _paginate_metric_query(model, query, offset, limit)


@router.get("/{machine_id}", response_model=MachineRead)
def get_machine(machine_id: int, db: Session = Depends(get_db)) -> Machine:
    """Return one machine by id."""
    return get_or_404(db, Machine, machine_id, "machine not found")


@router.patch("/{machine_id}", response_model=MachineRead)
def update_machine(machine_id: int, payload: MachineUpdate, db: Session = Depends(get_db)) -> Machine:
    """Patch a machine."""
    machine = get_or_404(db, Machine, machine_id, "machine not found")
    apply_patch(machine, payload.model_dump(exclude_unset=True))
    commit_or_409(db, "machine already exists for this platform or provisioner external id")
    db.refresh(machine)
    return machine


@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_machine(machine_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a machine."""
    machine = get_or_404(db, Machine, machine_id, "machine not found")
    db.delete(machine)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{machine_id}/metrics", response_model=PaginatedResponse[MachineMetricRead])
def list_machine_metric_history(
    machine_id: int,
    metric_type: Scope = Query(alias="type"),
    provider_id: int | None = None,
    start: date | None = None,
    end: date | None = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineMetricRead]:
    """List paginated metrics for one machine and metric type."""
    get_or_404(db, Machine, machine_id, "machine not found")
    model, query = _metric_query(metric_type, db, provider_id=provider_id, machine_id=machine_id, start=start, end=end)
    return _paginate_metric_query(model, query, offset, limit)


@router.get("/{machine_id}/flavor-history", response_model=list[MachineFlavorHistoryRead])
def list_machine_flavor_history(machine_id: int, db: Session = Depends(get_db)) -> list[MachineFlavorHistory]:
    """List flavor change history for one machine."""
    get_or_404(db, Machine, machine_id, "machine not found")
    return (
        db.query(MachineFlavorHistory)
        .filter(MachineFlavorHistory.machine_id == machine_id)
        .order_by(MachineFlavorHistory.changed_at.desc())
        .all()
    )
