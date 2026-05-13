"""Assistant-friendly read-only discovery routes."""

from __future__ import annotations

import json
from typing import Any, Callable, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.common import get_or_404
from app.api.routes.machines.metrics import METRIC_MODELS
from app.api.routes.machines.optimizations import serialize_machine_optimization
from internal.contracts.http.resources import (
    ApplicationOverviewRead,
    ApplicationRead,
    ApplicationSummaryRead,
    BoundedResponse,
    DiscoveryCatalogRead,
    DiscoveryRecordRead,
    MachineContextRead,
    MachineMetricLatestRead,
    MachineMetricRead,
    MachineOptimizationAction,
    MachineOptimizationRead,
    MachineOptimizationStatus,
    MachineRead,
    OptimizationRecommendationRead,
    PlatformRead,
    Scope,
)
from internal.domain import normalize_application_code, normalize_dimension, normalize_external_id, normalize_hostname
from internal.infra.db.models import Application, Machine, MachineOptimization, Platform

router = APIRouter(prefix="/discovery", tags=["Discovery"])

MAX_DISCOVERY_RESULTS = 100
DEFAULT_DISCOVERY_RESULTS = 25
ResourceT = TypeVar("ResourceT")


def _bounded_items(
    query: Any,
    transform: Callable[[Any], ResourceT],
    max_results: int,
    *order_by: Any,
) -> BoundedResponse[ResourceT]:
    """Return a bounded response without exposing pagination controls."""
    total = query.order_by(None).count()
    ordered = query.order_by(*order_by) if order_by else query
    rows = ordered.limit(max_results).all()
    items = [transform(row) for row in rows]
    return BoundedResponse(items=items, total=total, returned=len(items), truncated=total > len(items))


def _application_machine_query(db: Session, application: Application):
    """Build the machine query matching one application projection row."""
    return (
        db.query(Machine)
        .filter(Machine.application == application.name)
        .filter(func.coalesce(Machine.environment, "UNKNOWN") == application.environment)
        .filter(func.coalesce(Machine.region, "UNKNOWN") == application.region)
    )


def _application_join_condition() -> Any:
    """Return the SQL condition matching machines to application projection rows."""
    return and_(
        Machine.application == Application.name,
        func.coalesce(Machine.environment, "UNKNOWN") == Application.environment,
        func.coalesce(Machine.region, "UNKNOWN") == Application.region,
    )


def _machine_application(db: Session, machine: Machine) -> Application | None:
    """Return the application projection row represented by one machine."""
    if machine.application is None:
        return None
    return (
        db.query(Application)
        .filter(Application.name == machine.application)
        .filter(Application.environment == (machine.environment or "UNKNOWN"))
        .filter(Application.region == (machine.region or "UNKNOWN"))
        .one_or_none()
    )


def _latest_metrics(db: Session, machine_id: int) -> MachineMetricLatestRead:
    """Return latest metric samples for all metric scopes."""
    latest: dict[str, MachineMetricRead | None] = {}
    for scope, model in METRIC_MODELS.items():
        row = (
            db.query(model)
            .filter(model.machine_id == machine_id)
            .order_by(model.date.desc(), model.id.desc())
            .first()
        )
        latest[scope] = MachineMetricRead.model_validate(row) if row is not None else None
    return MachineMetricLatestRead(**latest)


def _current_optimization(db: Session, machine_id: int) -> MachineOptimizationRead | None:
    """Return the current optimization projection for one machine when available."""
    optimization = (
        db.query(MachineOptimization)
        .filter(MachineOptimization.machine_id == machine_id)
        .filter(MachineOptimization.is_current.is_(True))
        .one_or_none()
    )
    if optimization is None:
        return None
    return serialize_machine_optimization(optimization)


def _application_summary(db: Session, application: Application) -> ApplicationSummaryRead:
    """Build an assistant-friendly summary for one application projection row."""
    machine_query = _application_machine_query(db, application)
    machine_ids = machine_query.with_entities(Machine.id)
    optimization_query = (
        db.query(MachineOptimization)
        .filter(MachineOptimization.machine_id.in_(machine_ids))
        .filter(MachineOptimization.is_current.is_(True))
    )
    return ApplicationSummaryRead(
        application=ApplicationRead.model_validate(application),
        machine_count=machine_query.count(),
        platform_ids=[
            int(platform_id)
            for (platform_id,) in machine_query.with_entities(Machine.platform_id)
            .distinct()
            .order_by(Machine.platform_id.asc())
            .all()
        ],
        current_optimization_count=optimization_query.count(),
        current_optimizations_by_status={
            status: count
            for status, count in optimization_query.with_entities(
                MachineOptimization.status,
                func.count(MachineOptimization.id),
            )
            .group_by(MachineOptimization.status)
            .all()
        },
        current_optimizations_by_action={
            action: count
            for action, count in optimization_query.with_entities(
                MachineOptimization.action,
                func.count(MachineOptimization.id),
            )
            .group_by(MachineOptimization.action)
            .all()
        },
    )


def _application_overview(
    db: Session,
    application: Application,
    max_machines: int,
    max_optimizations: int,
) -> ApplicationOverviewRead:
    """Build the full assistant context for one application projection row."""
    summary = _application_summary(db, application)
    machine_query = _application_machine_query(db, application)
    machine_ids = machine_query.with_entities(Machine.id)
    optimization_query = (
        db.query(MachineOptimization)
        .filter(MachineOptimization.machine_id.in_(machine_ids))
        .filter(MachineOptimization.is_current.is_(True))
    )
    return ApplicationOverviewRead(
        application=summary.application,
        machine_count=summary.machine_count,
        platform_ids=summary.platform_ids,
        current_optimization_count=summary.current_optimization_count,
        current_optimizations_by_status=summary.current_optimizations_by_status,
        current_optimizations_by_action=summary.current_optimizations_by_action,
        machines=_bounded_items(
            machine_query,
            MachineRead.model_validate,
            max_machines,
            Machine.hostname.asc(),
            Machine.id.asc(),
        ),
        current_optimizations=_bounded_items(
            optimization_query,
            serialize_machine_optimization,
            max_optimizations,
            MachineOptimization.computed_at.desc(),
            MachineOptimization.id.desc(),
        ),
    )


def _machine_context(db: Session, machine: Machine) -> MachineContextRead:
    """Build the full assistant context for one machine."""
    application = _machine_application(db, machine)
    return MachineContextRead(
        machine=MachineRead.model_validate(machine),
        platform=PlatformRead.model_validate(machine.platform) if machine.platform is not None else None,
        application=ApplicationRead.model_validate(application) if application is not None else None,
        latest_metrics=_latest_metrics(db, machine.id),
        current_optimization=_current_optimization(db, machine.id),
    )


def _optimization_recommendation(db: Session, optimization: MachineOptimization) -> OptimizationRecommendationRead:
    """Build a current optimization recommendation with ownership context."""
    machine = optimization.machine
    application = _machine_application(db, machine)
    return OptimizationRecommendationRead(
        optimization=serialize_machine_optimization(optimization),
        machine=MachineRead.model_validate(machine),
        platform=PlatformRead.model_validate(machine.platform) if machine.platform is not None else None,
        application=ApplicationRead.model_validate(application) if application is not None else None,
    )


def _catalog(db: Session) -> DiscoveryCatalogRead:
    """Build the top-level discovery catalog."""
    environments = {
        value
        for (value,) in db.query(Application.environment).filter(Application.environment.is_not(None)).all()
        if value
    }
    environments.update(
        value
        for (value,) in db.query(Machine.environment).filter(Machine.environment.is_not(None)).all()
        if value
    )
    regions = {
        value
        for (value,) in db.query(Application.region).filter(Application.region.is_not(None)).all()
        if value
    }
    regions.update(value for (value,) in db.query(Machine.region).filter(Machine.region.is_not(None)).all() if value)
    return DiscoveryCatalogRead(
        platforms=[
            PlatformRead.model_validate(platform)
            for platform in db.query(Platform).order_by(Platform.name.asc(), Platform.id.asc()).all()
        ],
        environments=sorted(environments),
        regions=sorted(regions),
        metric_types=["cpu", "ram", "disk"],
        optimization_statuses=["ready", "partial", "error"],
        optimization_actions=["scale_up", "scale_down", "mixed", "keep", "insufficient_data", "unavailable"],
        totals={
            "platforms": db.query(func.count(Platform.id)).scalar() or 0,
            "applications": db.query(func.count(Application.id)).scalar() or 0,
            "machines": db.query(func.count(Machine.id)).scalar() or 0,
            "current_optimizations": (
                db.query(func.count(MachineOptimization.id))
                .filter(MachineOptimization.is_current.is_(True))
                .scalar()
                or 0
            ),
        },
    )


def _optimization_query(
    db: Session,
    platform_id: int | None = None,
    application: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    status: MachineOptimizationStatus | None = None,
    action: MachineOptimizationAction | None = None,
) -> Any:
    """Build a filtered query for current machine optimizations."""
    query = (
        db.query(MachineOptimization)
        .join(Machine, MachineOptimization.machine_id == Machine.id)
        .filter(MachineOptimization.is_current.is_(True))
    )
    normalized_application = normalize_application_code(application)
    normalized_environment = normalize_dimension(environment)
    normalized_region = normalize_dimension(region)
    if platform_id is not None:
        query = query.filter(Machine.platform_id == platform_id)
    if normalized_application is not None:
        query = query.filter(Machine.application == normalized_application)
    if normalized_environment is not None:
        query = query.filter(Machine.environment == normalized_environment)
    if normalized_region is not None:
        query = query.filter(Machine.region == normalized_region)
    if status is not None:
        query = query.filter(MachineOptimization.status == status)
    if action is not None:
        query = query.filter(MachineOptimization.action == action)
    return query


def _record_url(record_id: str) -> str:
    """Return a stable MCP URI for a fetchable discovery record."""
    return f"metrics-collector://records/{record_id}"


def _record_payload(record_id: str, record_type: str, title: str, payload: Any, metadata: dict[str, Any]) -> DiscoveryRecordRead:
    """Build a fetch-compatible text record from a structured payload."""
    if hasattr(payload, "model_dump"):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    return DiscoveryRecordRead(
        id=record_id,
        type=record_type,
        title=title,
        text=json.dumps(data, indent=2, sort_keys=True),
        url=_record_url(record_id),
        metadata=metadata,
    )


@router.get("/catalog", response_model=DiscoveryCatalogRead)
def get_discovery_catalog(db: Session = Depends(get_db)) -> DiscoveryCatalogRead:
    """Discover platforms, dimensions, metric scopes, and optimization vocabulary."""
    return _catalog(db)


@router.get("/applications", response_model=BoundedResponse[ApplicationSummaryRead])
def list_discovery_applications(
    name: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    platform_id: int | None = None,
    max_results: int = Query(default=DEFAULT_DISCOVERY_RESULTS, ge=1, le=MAX_DISCOVERY_RESULTS),
    db: Session = Depends(get_db),
) -> BoundedResponse[ApplicationSummaryRead]:
    """Discover application projection rows with operational counts."""
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
        )
        query = query.filter(Application.id.in_(application_ids))
    return _bounded_items(
        query,
        lambda application: _application_summary(db, application),
        max_results,
        Application.name.asc(),
        Application.environment.asc(),
        Application.region.asc(),
        Application.id.asc(),
    )


@router.get("/applications/{application_id}/overview", response_model=ApplicationOverviewRead)
def get_discovery_application_overview(
    application_id: int,
    max_machines: int = Query(default=DEFAULT_DISCOVERY_RESULTS, ge=1, le=MAX_DISCOVERY_RESULTS),
    max_optimizations: int = Query(default=DEFAULT_DISCOVERY_RESULTS, ge=1, le=MAX_DISCOVERY_RESULTS),
    db: Session = Depends(get_db),
) -> ApplicationOverviewRead:
    """Return machines and current optimizations for one application projection row."""
    application = get_or_404(db, Application, application_id, "application not found")
    return _application_overview(db, application, max_machines, max_optimizations)


@router.get("/machines/search", response_model=BoundedResponse[MachineRead])
def search_discovery_machines(
    q: str | None = None,
    hostname: str | None = None,
    external_id: str | None = None,
    application: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    platform_id: int | None = None,
    max_results: int = Query(default=DEFAULT_DISCOVERY_RESULTS, ge=1, le=MAX_DISCOVERY_RESULTS),
    db: Session = Depends(get_db),
) -> BoundedResponse[MachineRead]:
    """Find machines by hostname, external id, application, environment, region, or platform."""
    query = db.query(Machine)
    normalized_hostname = normalize_hostname(hostname)
    normalized_external_id = normalize_external_id(external_id)
    normalized_application = normalize_application_code(application)
    normalized_environment = normalize_dimension(environment)
    normalized_region = normalize_dimension(region)
    if normalized_hostname is not None:
        query = query.filter(Machine.hostname == normalized_hostname)
    if normalized_external_id is not None:
        query = query.filter(Machine.external_id == normalized_external_id)
    if normalized_application is not None:
        query = query.filter(Machine.application == normalized_application)
    if normalized_environment is not None:
        query = query.filter(Machine.environment == normalized_environment)
    if normalized_region is not None:
        query = query.filter(Machine.region == normalized_region)
    if platform_id is not None:
        query = query.filter(Machine.platform_id == platform_id)

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
            conditions.extend([Machine.environment.contains(dimension_term), Machine.region.contains(dimension_term)])
        if conditions:
            query = query.filter(or_(*conditions))

    return _bounded_items(query, MachineRead.model_validate, max_results, Machine.hostname.asc(), Machine.id.asc())


@router.get("/machines/{machine_id}/context", response_model=MachineContextRead)
def get_discovery_machine_context(
    machine_id: int,
    db: Session = Depends(get_db),
) -> MachineContextRead:
    """Return machine ownership, latest metrics, and current optimization context."""
    machine = get_or_404(db, Machine, machine_id, "machine not found")
    return _machine_context(db, machine)


@router.get("/optimizations/current", response_model=BoundedResponse[OptimizationRecommendationRead])
def list_discovery_current_optimizations(
    platform_id: int | None = None,
    application: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    status: MachineOptimizationStatus | None = None,
    action: MachineOptimizationAction | None = None,
    max_results: int = Query(default=DEFAULT_DISCOVERY_RESULTS, ge=1, le=MAX_DISCOVERY_RESULTS),
    db: Session = Depends(get_db),
) -> BoundedResponse[OptimizationRecommendationRead]:
    """Discover current optimization recommendations with machine context."""
    query = _optimization_query(db, platform_id, application, environment, region, status, action)
    return _bounded_items(
        query,
        lambda optimization: _optimization_recommendation(db, optimization),
        max_results,
        MachineOptimization.computed_at.desc(),
        MachineOptimization.id.desc(),
    )


@router.get("/records/{record_id:path}", response_model=DiscoveryRecordRead)
def fetch_discovery_record(record_id: str, db: Session = Depends(get_db)) -> DiscoveryRecordRead:
    """Fetch a complete text record for MCP search/fetch clients."""
    if record_id == "catalog":
        return _record_payload(
            record_id,
            "catalog",
            "Metrics Collector discovery catalog",
            _catalog(db),
            {"source": "discovery_catalog"},
        )

    record_type, separator, raw_id = record_id.partition(":")
    if not separator or not raw_id.isdigit():
        raise HTTPException(status_code=404, detail="record not found")
    object_id = int(raw_id)
    if record_type == "application":
        application = get_or_404(db, Application, object_id, "record not found")
        overview = _application_overview(db, application, MAX_DISCOVERY_RESULTS, MAX_DISCOVERY_RESULTS)
        return _record_payload(
            record_id,
            "application",
            f"{application.name} {application.environment} {application.region}",
            overview,
            {
                "application_id": application.id,
                "name": application.name,
                "environment": application.environment,
                "region": application.region,
            },
        )
    if record_type == "machine":
        machine = get_or_404(db, Machine, object_id, "record not found")
        return _record_payload(
            record_id,
            "machine",
            machine.hostname,
            _machine_context(db, machine),
            {"machine_id": machine.id, "hostname": machine.hostname, "platform_id": machine.platform_id},
        )
    if record_type == "optimization":
        optimization = get_or_404(db, MachineOptimization, object_id, "record not found")
        return _record_payload(
            record_id,
            "optimization",
            f"{optimization.machine.hostname} optimization {optimization.action}",
            _optimization_recommendation(db, optimization),
            {
                "optimization_id": optimization.id,
                "machine_id": optimization.machine_id,
                "status": optimization.status,
                "action": optimization.action,
            },
        )
    raise HTTPException(status_code=404, detail="record not found")
