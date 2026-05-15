"""Machine read/delete and flavor history routes."""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import get_or_404, paginate_query
from internal.domain import (
    normalize_application_code,
    normalize_dimension,
    normalize_external_id,
    normalize_hostname,
)
from internal.contracts.http.resources import (
    MachineFlavorHistoryRead,
    MachineRead,
    PaginatedResponse,
)
from internal.infra.db.models import Application, Machine, MachineFlavorHistory


router = APIRouter(prefix="/machines", tags=["Machines"])


@router.get("", response_model=PaginatedResponse[MachineRead])
def list_machines(
    q: str | None = None,
    platform_id: int | None = None,
    application_id: int | None = None,
    application_name: str | None = None,
    application: str | None = None,
    source_provisioner_id: int | None = None,
    hostname: str | None = None,
    external_id: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineRead]:
    """List machines with optional platform, ownership, identity, and text filters."""
    query = db.query(Machine)
    normalized_application = normalize_application_code(application)
    normalized_application_name = normalize_application_code(application_name)
    normalized_environment = normalize_dimension(environment)
    normalized_region = normalize_dimension(region)
    normalized_hostname = normalize_hostname(hostname)
    normalized_external_id = normalize_external_id(external_id)
    if platform_id is not None:
        query = query.filter(Machine.platform_id == platform_id)
    if application_id is not None:
        application_row = get_or_404(db, Application, application_id, "application not found")
        query = (
            query.filter(Machine.application == application_row.name)
            .filter(func.coalesce(Machine.environment, "UNKNOWN") == application_row.environment)
            .filter(func.coalesce(Machine.region, "UNKNOWN") == application_row.region)
        )
    if normalized_application is not None:
        query = query.filter(Machine.application == normalized_application)
    if normalized_application_name is not None:
        query = query.filter(Machine.application == normalized_application_name)
    if source_provisioner_id is not None:
        query = query.filter(Machine.source_provisioner_id == source_provisioner_id)
    if normalized_hostname is not None:
        query = query.filter(Machine.hostname == normalized_hostname)
    if normalized_external_id is not None:
        query = query.filter(Machine.external_id == normalized_external_id)
    if normalized_environment is not None:
        query = query.filter(Machine.environment == normalized_environment)
    if normalized_region is not None:
        query = query.filter(Machine.region == normalized_region)

    term = q.strip() if q is not None else ""
    if term:
        hostname_term = normalize_hostname(term)
        external_term = normalize_external_id(term)
        application_term = normalize_application_code(term)
        dimension_term = normalize_dimension(term)
        conditions = []
        if hostname_term is not None:
            conditions.append(Machine.hostname.contains(hostname_term))
        if external_term is not None:
            conditions.append(Machine.external_id.contains(external_term))
        if application_term is not None:
            conditions.append(Machine.application.contains(application_term))
        if dimension_term is not None:
            conditions.extend(
                [
                    Machine.environment.contains(dimension_term),
                    Machine.region.contains(dimension_term),
                ]
            )
        if conditions:
            query = query.filter(or_(*conditions))
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
