"""Application read, stats, and sync routes."""

from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import get_or_404, paginate_query
from app.api.routes.machines.metrics import METRIC_MODELS
from app.api.routes.machines.optimizations import RESOURCE_UNITS, serialize_machine_optimization
from internal.domain import normalize_application_code, normalize_dimension
from internal.contracts.http.resources import (
    ApplicationDimensionListRead,
    ApplicationOptimizationResourceSummaryRead,
    ApplicationOptimizationSummaryRead,
    ApplicationRead,
    ApplicationResourceStatsRead,
    ApplicationStatsRead,
    ApplicationSyncType,
    MachineOptimizationRead,
    MachineRead,
    PaginatedResponse,
    Scope,
    TaskEnqueueResponse,
)
from internal.infra.db.models import Application, Machine, MachineOptimization
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import (
    DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK,
    SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK,
    SYNC_APPLICATION_METRICS_TASK,
)


router = APIRouter(prefix="/applications", tags=["Applications"])


def _application_join_condition():
    """Return the SQL condition matching machines to application projection rows."""
    return and_(
        Machine.application == Application.name,
        func.coalesce(Machine.environment, "UNKNOWN") == Application.environment,
        func.coalesce(Machine.region, "UNKNOWN") == Application.region,
    )


def _application_machine_query(db: Session, application: Application):
    """Build the current machine query matching one application projection row."""
    return (
        db.query(Machine)
        .filter(Machine.application == application.name)
        .filter(func.coalesce(Machine.environment, "UNKNOWN") == application.environment)
        .filter(func.coalesce(Machine.region, "UNKNOWN") == application.region)
    )


def _filtered_application_query(
    db: Session,
    *,
    q: str | None = None,
    name: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    platform_id: int | None = None,
):
    """Build the shared application collection query."""
    query = db.query(Application)
    normalized_name = normalize_application_code(name)
    normalized_environment = normalize_dimension(environment)
    normalized_region = normalize_dimension(region)
    if normalized_name is not None:
        query = query.filter(Application.name == normalized_name)
    if normalized_environment is not None:
        query = query.filter(Application.environment == normalized_environment)
    if normalized_region is not None:
        query = query.filter(Application.region == normalized_region)
    if platform_id is not None:
        application_ids = (
            db.query(Application.id)
            .join(Machine, _application_join_condition())
            .filter(Machine.platform_id == platform_id)
            .distinct()
        )
        query = query.filter(Application.id.in_(application_ids))

    term = q.strip() if q is not None else ""
    if term:
        name_term = normalize_application_code(term)
        dimension_term = normalize_dimension(term)
        conditions = []
        if name_term is not None:
            conditions.append(Application.name.contains(name_term))
        if dimension_term is not None:
            conditions.extend(
                [
                    Application.environment.contains(dimension_term),
                    Application.region.contains(dimension_term),
                ]
            )
        if conditions:
            query = query.filter(or_(*conditions))
    return query


def _application_machine_ids(db: Session, application: Application) -> list[int]:
    """Return machine ids represented by one application projection row."""
    return [
        int(machine_id)
        for (machine_id,) in _application_machine_query(db, application).with_entities(Machine.id).all()
    ]


def _latest_metric_date(db: Session, machine_ids: list[int]):
    """Return the latest metric date for any scope in an application."""
    if not machine_ids:
        return None
    latest_dates = [
        db.query(func.max(model.date))
        .filter(model.machine_id.in_(machine_ids))
        .scalar()
        for model in METRIC_MODELS.values()
    ]
    available_dates = [metric_date for metric_date in latest_dates if metric_date is not None]
    return max(available_dates) if available_dates else None


def _application_stats_resource(
    db: Session,
    *,
    scope: Scope,
    machine_ids: list[int],
    allocated: float,
    start_date,
    end_date,
) -> ApplicationResourceStatsRead:
    """Build one resource stats block."""
    average_usage = None
    peak_usage = None
    sample_count = 0
    if machine_ids and start_date is not None and end_date is not None:
        model = METRIC_MODELS[scope]
        average_usage, peak_usage, sample_count = (
            db.query(func.avg(model.value), func.max(model.value), func.count(model.id))
            .filter(model.machine_id.in_(machine_ids))
            .filter(model.date >= start_date)
            .filter(model.date <= end_date)
            .one()
        )
    return ApplicationResourceStatsRead(
        allocated=allocated,
        allocated_unit=RESOURCE_UNITS[scope],
        average_usage_percent=float(average_usage) if average_usage is not None else None,
        peak_usage_percent=float(peak_usage) if peak_usage is not None else None,
        sample_count=int(sample_count or 0),
    )


def _optimization_confidence(status_counts: Counter[str], optimization_count: int) -> tuple[str, float, str]:
    """Derive deterministic confidence from the aggregated optimization statuses."""
    if optimization_count == 0:
        return "none", 0.0, "No current optimization recommendation is available for this application."
    if status_counts.get("error", 0) > 0:
        return "low", 0.3, "At least one current recommendation is in error."
    if status_counts.get("partial", 0) > 0:
        return "medium", 0.6, "Some current recommendations are partial because supporting data is incomplete."
    return "high", 0.9, "All current recommendations are ready."


@router.get("", response_model=PaginatedResponse[ApplicationRead])
def list_applications(
    q: str | None = None,
    name: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    platform_id: int | None = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ApplicationRead]:
    """List applications with optional identity, platform, and text filters."""
    query = _filtered_application_query(
        db,
        q=q,
        name=name,
        environment=environment,
        region=region,
        platform_id=platform_id,
    )
    return paginate_query(
        query,
        ApplicationRead,
        pagination,
        Application.name.asc(),
        Application.environment.asc(),
        Application.region.asc(),
        Application.id.asc(),
    )


@router.post(
    "/sync",
    response_model=TaskEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_application_sync(
    sync_type: ApplicationSyncType = Query(alias="type"),
) -> TaskEnqueueResponse:
    """Enqueue one application sync pipeline."""
    task_name = (
        SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK
        if sync_type == "inventory_discovery"
        else DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK
    )
    task = enqueue_celery_task(task_name)
    return TaskEnqueueResponse(task_id=task.id)


@router.get("/regions", response_model=ApplicationDimensionListRead)
def list_application_regions(
    environment: str | None = None,
    platform_id: int | None = None,
    db: Session = Depends(get_db),
) -> ApplicationDimensionListRead:
    """List distinct application regions, optionally filtered by environment or platform."""
    query = _filtered_application_query(db, environment=environment, platform_id=platform_id)
    values = [
        value
        for (value,) in query.with_entities(Application.region)
        .filter(Application.region.is_not(None))
        .distinct()
        .order_by(Application.region.asc())
        .all()
        if value
    ]
    return ApplicationDimensionListRead(items=values, total=len(values))


@router.get("/environments", response_model=ApplicationDimensionListRead)
def list_application_environments(
    region: str | None = None,
    platform_id: int | None = None,
    db: Session = Depends(get_db),
) -> ApplicationDimensionListRead:
    """List distinct application environments, optionally filtered by region or platform."""
    query = _filtered_application_query(db, region=region, platform_id=platform_id)
    values = [
        value
        for (value,) in query.with_entities(Application.environment)
        .filter(Application.environment.is_not(None))
        .distinct()
        .order_by(Application.environment.asc())
        .all()
        if value
    ]
    return ApplicationDimensionListRead(items=values, total=len(values))


@router.get("/{application_id}", response_model=ApplicationRead)
def get_application(application_id: int, db: Session = Depends(get_db)) -> Application:
    """Return one application by id."""
    return get_or_404(db, Application, application_id, "application not found")


@router.get("/{application_id}/machines", response_model=PaginatedResponse[MachineRead])
def list_application_machines(
    application_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineRead]:
    """List machines represented by one application projection row."""
    application = get_or_404(db, Application, application_id, "application not found")
    query = _application_machine_query(db, application)
    return paginate_query(query, MachineRead, pagination, Machine.hostname.asc(), Machine.id.asc())


@router.get("/{application_id}/stats", response_model=ApplicationStatsRead)
def get_application_stats(
    application_id: int,
    window_days: int = Query(default=7),
    db: Session = Depends(get_db),
) -> ApplicationStatsRead:
    """Return allocated capacity and observed usage for one application."""
    if window_days not in {7, 15, 30}:
        raise HTTPException(status_code=422, detail="window_days must be one of 7, 15, or 30")
    application = get_or_404(db, Application, application_id, "application not found")
    machines = _application_machine_query(db, application).all()
    machine_ids = [machine.id for machine in machines]
    end_date = _latest_metric_date(db, machine_ids)
    start_date = end_date - timedelta(days=window_days - 1) if end_date is not None else None
    allocated = {
        "cpu": sum(machine.cpu or 0 for machine in machines),
        "ram": sum(machine.ram_mb or 0 for machine in machines),
        "disk": sum(machine.disk_mb or 0 for machine in machines),
    }
    return ApplicationStatsRead(
        application=ApplicationRead.model_validate(application),
        window_days=window_days,
        start_date=start_date,
        end_date=end_date,
        machine_count=len(machines),
        resources={
            scope: _application_stats_resource(
                db,
                scope=scope,
                machine_ids=machine_ids,
                allocated=float(allocated[scope]),
                start_date=start_date,
                end_date=end_date,
            )
            for scope in ("cpu", "ram", "disk")
        },
    )


@router.post("/{application_id}/metrics/sync", response_model=TaskEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_single_application_metrics_sync(
    application_id: int,
    db: Session = Depends(get_db),
) -> TaskEnqueueResponse:
    """Enqueue a metrics sync for one application projection row."""
    get_or_404(db, Application, application_id, "application not found")
    task = enqueue_celery_task(SYNC_APPLICATION_METRICS_TASK, args=[application_id])
    return TaskEnqueueResponse(task_id=task.id)


@router.get("/{application_id}/optimizations", response_model=PaginatedResponse[MachineOptimizationRead])
def list_application_optimizations(
    application_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[MachineOptimizationRead]:
    """List optimizations for machines represented by one application row."""
    application = get_or_404(db, Application, application_id, "application not found")
    machine_query = _application_machine_query(db, application).with_entities(Machine.id)
    query = db.query(MachineOptimization).filter(MachineOptimization.machine_id.in_(machine_query))
    return paginate_query(
        query,
        MachineOptimizationRead,
        pagination,
        MachineOptimization.computed_at.desc(),
        MachineOptimization.id.desc(),
        transform=serialize_machine_optimization,
    )


@router.get("/{application_id}/optimizations/summary", response_model=ApplicationOptimizationSummaryRead)
def get_application_optimizations_summary(
    application_id: int,
    db: Session = Depends(get_db),
) -> ApplicationOptimizationSummaryRead:
    """Return aggregated current optimization recommendations for one application."""
    application = get_or_404(db, Application, application_id, "application not found")
    machine_ids = _application_machine_ids(db, application)
    optimizations = (
        db.query(MachineOptimization)
        .filter(MachineOptimization.machine_id.in_(machine_ids))
        .order_by(MachineOptimization.computed_at.desc(), MachineOptimization.id.desc())
        .all()
        if machine_ids
        else []
    )
    serialized_optimizations = [serialize_machine_optimization(optimization) for optimization in optimizations]
    status_counts = Counter(optimization.status for optimization in serialized_optimizations)
    action_counts = Counter(optimization.action for optimization in serialized_optimizations)
    confidence, confidence_score, justification = _optimization_confidence(status_counts, len(serialized_optimizations))

    resource_summaries = {}
    for scope in ("cpu", "ram", "disk"):
        resource_reads = [optimization.resources[scope] for optimization in serialized_optimizations]
        current_values = [resource.current for resource in resource_reads if resource.current is not None]
        recommended_values = [resource.recommended for resource in resource_reads if resource.recommended is not None]
        current_total = float(sum(current_values)) if current_values else None
        recommended_total = float(sum(recommended_values)) if recommended_values else None
        delta = (
            float(recommended_total - current_total)
            if current_total is not None and recommended_total is not None
            else None
        )
        utilization_values = [
            resource.utilization_percent
            for resource in resource_reads
            if resource.utilization_percent is not None
        ]
        reasons = sorted({resource.reason for resource in resource_reads if resource.reason})
        resource_summaries[scope] = ApplicationOptimizationResourceSummaryRead(
            unit=RESOURCE_UNITS[scope],
            current_total=current_total,
            recommended_total=recommended_total,
            delta=delta,
            reclaimable_capacity=max(0.0, -delta) if delta is not None else 0.0,
            additional_capacity=max(0.0, delta) if delta is not None else 0.0,
            recommendations_by_status=dict(Counter(resource.status for resource in resource_reads)),
            recommendations_by_action=dict(Counter(resource.action for resource in resource_reads)),
            average_utilization_percent=(
                float(sum(utilization_values) / len(utilization_values))
                if utilization_values
                else None
            ),
            reasons=reasons,
        )

    return ApplicationOptimizationSummaryRead(
        application=ApplicationRead.model_validate(application),
        machine_count=len(machine_ids),
        optimization_count=len(serialized_optimizations),
        recommendations_by_status=dict(status_counts),
        recommendations_by_action=dict(action_counts),
        resources=resource_summaries,
        confidence=confidence,
        confidence_score=confidence_score,
        justification=justification,
    )
