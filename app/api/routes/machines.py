"""Machine routes plus provider and provisioner routes grouped under /machines."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404
from internal.contracts.http.resources import (
    CapsuleProvisionerCreate,
    CapsuleProvisionerRead,
    CapsuleProvisionerUpdate,
    DynatraceProviderCreate,
    DynatraceProviderRead,
    DynatraceProviderUpdate,
    DynatraceProvisionerCreate,
    DynatraceProvisionerRead,
    DynatraceProvisionerUpdate,
    MachineCreate,
    MachineFlavorHistoryRead,
    MachineMetricRead,
    MachineRead,
    MachineUpdate,
    PaginatedResponse,
    PrometheusProviderCreate,
    PrometheusProviderRead,
    PrometheusProviderUpdate,
    ProviderRead,
    ProvisionerRead,
    Scope,
    TaskEnqueueResponse,
)
from internal.infra.db.models import (
    PROVISIONER_PROVIDER_TYPE_CONFLICT_DETAIL,
    Machine,
    MachineCPUMetric,
    MachineDiskMetric,
    MachineFlavorHistory,
    MachineProvider,
    MachineProviderProvisioner,
    MachineProvisioner,
    MachineRAMMetric,
    find_provider_type_conflict,
)
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import RUN_PROVISIONER_TASK


router = APIRouter(prefix="/machines", tags=["machines"])
providers_router = APIRouter(prefix="/providers", tags=["machines"])
provisioners_router = APIRouter(prefix="/provisioners", tags=["machines"])

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


def _load_provider(db: Session, provider_id: int) -> MachineProvider:
    """Load a provider with the relations needed by the API responses."""
    provider = (
        db.query(MachineProvider)
        .options(selectinload(MachineProvider.provisioners))
        .filter(MachineProvider.id == provider_id)
        .one_or_none()
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    return provider


def _load_provider_of_type(db: Session, provider_id: int, connector_type: str) -> MachineProvider:
    """Load a provider and enforce the expected typed sub-route."""
    provider = _load_provider(db, provider_id)
    if provider.type != connector_type:
        raise HTTPException(status_code=404, detail="provider not found")
    return provider


def _load_provisioners_for_provider(
    db: Session,
    provisioner_ids: list[int],
    platform_id: int,
    provider_type: str,
    provider_id: int | None = None,
) -> list[MachineProvisioner]:
    """Resolve attached provisioners and validate their platform ownership."""
    provisioners: list[MachineProvisioner] = []
    for provisioner_id in provisioner_ids:
        provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
        if provisioner.platform_id != platform_id:
            raise HTTPException(status_code=400, detail="provider and provisioners must belong to the same platform")
        if find_provider_type_conflict(provisioner, provider_type, provider_id=provider_id) is not None:
            raise HTTPException(status_code=409, detail=PROVISIONER_PROVIDER_TYPE_CONFLICT_DETAIL)
        provisioners.append(provisioner)
    return provisioners


def _ensure_provider_platform_matches_provisioners(provider: MachineProvider, platform_id: int) -> None:
    """Prevent moving a provider to a platform that mismatches its provisioners."""
    for provisioner in provider.provisioners:
        if provisioner.platform_id != platform_id:
            raise HTTPException(status_code=400, detail="provider and provisioners must belong to the same platform")


def _prometheus_read_model(provider: MachineProvider) -> PrometheusProviderRead:
    """Build the typed read model without exposing the raw config blob."""
    return PrometheusProviderRead(
        **ProviderRead.model_validate(provider).model_dump(),
        url=str(provider.config.get("url", "")),
        query=str(provider.config.get("query", "")),
    )


def _dynatrace_provider_read_model(provider: MachineProvider) -> DynatraceProviderRead:
    """Build the Dynatrace read model while replacing the token with a flag."""
    return DynatraceProviderRead(
        **ProviderRead.model_validate(provider).model_dump(),
        url=str(provider.config.get("url", "")),
        has_token=bool(provider.config.get("token")),
    )


def _load_provisioner_of_type(db: Session, provisioner_id: int, connector_type: str) -> MachineProvisioner:
    """Load a provisioner and validate the typed sub-route being used."""
    provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
    if provisioner.type != connector_type:
        raise HTTPException(status_code=404, detail="provisioner not found")
    return provisioner


def _ensure_provisioner_platform_can_change(provisioner: MachineProvisioner, platform_id: int) -> None:
    """Protect platform moves that would break linked machines or providers."""
    if platform_id == provisioner.platform_id:
        return
    if provisioner.machines:
        raise HTTPException(status_code=409, detail="cannot move provisioner with linked machines")
    for provider in provisioner.providers:
        if provider.platform_id != platform_id:
            raise HTTPException(status_code=400, detail="provider and provisioner must belong to the same platform")


def _capsule_read_model(provisioner: MachineProvisioner) -> CapsuleProvisionerRead:
    """Build the Capsule-specific read model without returning the token."""
    return CapsuleProvisionerRead(
        **ProvisionerRead.model_validate(provisioner).model_dump(),
        has_token=bool(provisioner.config.get("token")),
    )


def _dynatrace_provisioner_read_model(provisioner: MachineProvisioner) -> DynatraceProvisionerRead:
    """Build the Dynatrace read model with visible URL and hidden token."""
    return DynatraceProvisionerRead(
        **ProvisionerRead.model_validate(provisioner).model_dump(),
        url=str(provisioner.config.get("url", "")),
        has_token=bool(provisioner.config.get("token")),
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


@router.get("/{machine_id:int}/metrics", response_model=PaginatedResponse[MachineMetricRead])
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


@router.get("/{machine_id:int}/flavor-history", response_model=list[MachineFlavorHistoryRead])
def list_machine_flavor_history(machine_id: int, db: Session = Depends(get_db)) -> list[MachineFlavorHistory]:
    """List flavor change history for one machine."""
    get_or_404(db, Machine, machine_id, "machine not found")
    return (
        db.query(MachineFlavorHistory)
        .filter(MachineFlavorHistory.machine_id == machine_id)
        .order_by(MachineFlavorHistory.changed_at.desc())
        .all()
    )


@providers_router.post("/prometheus", response_model=PrometheusProviderRead, status_code=status.HTTP_201_CREATED)
def create_prometheus_provider(
    payload: PrometheusProviderCreate,
    db: Session = Depends(get_db),
) -> PrometheusProviderRead:
    """Create a typed Prometheus provider."""
    provisioners = _load_provisioners_for_provider(
        db,
        payload.provisioner_ids,
        payload.platform_id,
        provider_type="prometheus",
    )
    provider = MachineProvider(
        platform_id=payload.platform_id,
        name=payload.name,
        type="prometheus",
        scope=payload.scope,
        config={"url": str(payload.url), "query": payload.query},
        enabled=payload.enabled,
        provisioners=provisioners,
    )
    db.add(provider)
    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _prometheus_read_model(_load_provider(db, provider.id))


@providers_router.post("/dynatrace", response_model=DynatraceProviderRead, status_code=status.HTTP_201_CREATED)
def create_dynatrace_provider(
    payload: DynatraceProviderCreate,
    db: Session = Depends(get_db),
) -> DynatraceProviderRead:
    """Create a typed Dynatrace provider."""
    provisioners = _load_provisioners_for_provider(
        db,
        payload.provisioner_ids,
        payload.platform_id,
        provider_type="dynatrace",
    )
    provider = MachineProvider(
        platform_id=payload.platform_id,
        name=payload.name,
        type="dynatrace",
        scope=payload.scope,
        config={"url": str(payload.url), "token": payload.token},
        enabled=payload.enabled,
        provisioners=provisioners,
    )
    db.add(provider)
    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _dynatrace_provider_read_model(_load_provider(db, provider.id))


@providers_router.get("", response_model=list[ProviderRead])
def list_providers(
    platform_id: int | None = None,
    scope: Scope | None = None,
    enabled: bool | None = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[MachineProvider]:
    """List providers through the generic view.

    This endpoint intentionally exposes shared metadata only and keeps
    provider-specific configuration behind typed sub-routes.
    """
    query = db.query(MachineProvider).options(selectinload(MachineProvider.provisioners))
    if platform_id is not None:
        query = query.filter(MachineProvider.platform_id == platform_id)
    if scope is not None:
        query = query.filter(MachineProvider.scope == scope)
    if enabled is not None:
        query = query.filter(MachineProvider.enabled.is_(enabled))
    return query.offset(offset).limit(limit).all()


@providers_router.get("/{provider_id}", response_model=ProviderRead)
def get_provider(provider_id: int, db: Session = Depends(get_db)) -> MachineProvider:
    """Return a provider through the generic public representation."""
    return _load_provider(db, provider_id)


@providers_router.get("/{provider_id}/prometheus", response_model=PrometheusProviderRead)
def get_prometheus_provider(provider_id: int, db: Session = Depends(get_db)) -> PrometheusProviderRead:
    """Return the Prometheus-specific configuration view for one provider."""
    return _prometheus_read_model(_load_provider_of_type(db, provider_id, "prometheus"))


@providers_router.get("/{provider_id}/dynatrace", response_model=DynatraceProviderRead)
def get_dynatrace_provider(provider_id: int, db: Session = Depends(get_db)) -> DynatraceProviderRead:
    """Return the Dynatrace-specific configuration view for one provider."""
    return _dynatrace_provider_read_model(_load_provider_of_type(db, provider_id, "dynatrace"))


@providers_router.patch("/{provider_id}/prometheus", response_model=PrometheusProviderRead)
def update_prometheus_provider(
    provider_id: int,
    payload: PrometheusProviderUpdate,
    db: Session = Depends(get_db),
) -> PrometheusProviderRead:
    """Patch a Prometheus provider through its typed sub-route.

    The route updates shared provider fields directly and rewrites the
    typed configuration inside encrypted storage when `url` or `query` change.
    """
    provider = _load_provider_of_type(db, provider_id, "prometheus")
    values = payload.model_dump(exclude_unset=True, exclude={"scope", "url", "query"})
    target_platform_id = values.get("platform_id", provider.platform_id)

    if payload.scope is not None:
        provider.scope = payload.scope

    if "platform_id" in values:
        _ensure_provider_platform_matches_provisioners(provider, target_platform_id)

    apply_patch(provider, values)

    config = dict(provider.config)
    if payload.url is not None:
        config["url"] = str(payload.url)
    if payload.query is not None:
        config["query"] = payload.query
    provider.config = config

    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _prometheus_read_model(_load_provider(db, provider.id))


@providers_router.patch("/{provider_id}/dynatrace", response_model=DynatraceProviderRead)
def update_dynatrace_provider(
    provider_id: int,
    payload: DynatraceProviderUpdate,
    db: Session = Depends(get_db),
) -> DynatraceProviderRead:
    """Patch a Dynatrace provider without ever returning the raw token.

    Omitting `token` preserves the current secret, while providing one
    replaces the encrypted value stored in `config`.
    """
    provider = _load_provider_of_type(db, provider_id, "dynatrace")
    values = payload.model_dump(exclude_unset=True, exclude={"scope", "url", "token"})
    target_platform_id = values.get("platform_id", provider.platform_id)

    if payload.scope is not None:
        provider.scope = payload.scope

    if "platform_id" in values:
        _ensure_provider_platform_matches_provisioners(provider, target_platform_id)

    apply_patch(provider, values)

    config = dict(provider.config)
    if payload.url is not None:
        config["url"] = str(payload.url)
    if payload.token is not None:
        config["token"] = payload.token
    provider.config = config

    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _dynatrace_provider_read_model(_load_provider(db, provider.id))


@providers_router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a provider and its association rows."""
    provider = _load_provider(db, provider_id)
    db.delete(provider)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@providers_router.get("/{provider_id}/provisioners", response_model=list[ProvisionerRead])
def list_provider_provisioners(provider_id: int, db: Session = Depends(get_db)) -> list[MachineProvisioner]:
    """List the provisioners currently attached to a provider."""
    provider = _load_provider(db, provider_id)
    return provider.provisioners


@providers_router.post("/{provider_id}/provisioners/{provisioner_id}", response_model=ProviderRead)
def attach_provider_provisioner(
    provider_id: int,
    provisioner_id: int,
    db: Session = Depends(get_db),
) -> MachineProvider:
    """Attach a provisioner to a provider after platform validation."""
    provider = _load_provider(db, provider_id)
    provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
    if provisioner.platform_id != provider.platform_id:
        raise HTTPException(status_code=400, detail="provider and provisioner must belong to the same platform")
    if provisioner not in provider.provisioners:
        if find_provider_type_conflict(provisioner, provider.type, provider_id=provider.id) is not None:
            raise HTTPException(status_code=409, detail=PROVISIONER_PROVIDER_TYPE_CONFLICT_DETAIL)
        provider.provisioners.append(provisioner)
    commit_or_409(db, "provider/provisioner association already exists")
    return _load_provider(db, provider_id)


@providers_router.delete("/{provider_id}/provisioners/{provisioner_id}", status_code=status.HTTP_204_NO_CONTENT)
def detach_provider_provisioner(
    provider_id: int,
    provisioner_id: int,
    db: Session = Depends(get_db),
) -> Response:
    """Detach a provisioner from a provider if the pair exists."""
    provider = _load_provider(db, provider_id)
    provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
    if provisioner.platform_id != provider.platform_id:
        raise HTTPException(status_code=400, detail="provider and provisioner must belong to the same platform")
    if provisioner in provider.provisioners:
        provider.provisioners.remove(provisioner)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@provisioners_router.post("/capsule", response_model=CapsuleProvisionerRead, status_code=status.HTTP_201_CREATED)
def create_capsule_provisioner(
    payload: CapsuleProvisionerCreate,
    db: Session = Depends(get_db),
) -> CapsuleProvisionerRead:
    """Create a Capsule provisioner from a typed payload.

    The token is persisted in encrypted `config` and replaced by `has_token`
    in the response body.
    """
    provisioner = MachineProvisioner(
        platform_id=payload.platform_id,
        name=payload.name,
        type="capsule",
        config={"token": payload.token},
        enabled=payload.enabled,
        cron=payload.cron,
    )
    db.add(provisioner)
    commit_or_409(db, "provisioner name already exists for this platform")
    db.refresh(provisioner)
    return _capsule_read_model(provisioner)


@provisioners_router.post("/dynatrace", response_model=DynatraceProvisionerRead, status_code=status.HTTP_201_CREATED)
def create_dynatrace_provisioner(
    payload: DynatraceProvisionerCreate,
    db: Session = Depends(get_db),
) -> DynatraceProvisionerRead:
    """Create a Dynatrace provisioner with typed URL and token inputs.

    The generic provisioner fields stay first-class columns, while the
    Dynatrace-specific configuration is stored in encrypted `config`.
    """
    provisioner = MachineProvisioner(
        platform_id=payload.platform_id,
        name=payload.name,
        type="dynatrace",
        config={"url": str(payload.url), "token": payload.token},
        enabled=payload.enabled,
        cron=payload.cron,
    )
    db.add(provisioner)
    commit_or_409(db, "provisioner name already exists for this platform")
    db.refresh(provisioner)
    return _dynatrace_provisioner_read_model(provisioner)


@provisioners_router.get("", response_model=list[ProvisionerRead])
def list_provisioners(
    platform_id: int | None = None,
    enabled: bool | None = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[MachineProvisioner]:
    """List provisioners through the generic metadata view."""
    query = db.query(MachineProvisioner)
    if platform_id is not None:
        query = query.filter(MachineProvisioner.platform_id == platform_id)
    if enabled is not None:
        query = query.filter(MachineProvisioner.enabled.is_(enabled))
    return query.offset(offset).limit(limit).all()


@provisioners_router.get("/{provisioner_id}", response_model=ProvisionerRead)
def get_provisioner(provisioner_id: int, db: Session = Depends(get_db)) -> MachineProvisioner:
    """Return one provisioner without exposing its typed config."""
    return get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")


@provisioners_router.get("/{provisioner_id}/capsule", response_model=CapsuleProvisionerRead)
def get_capsule_provisioner(provisioner_id: int, db: Session = Depends(get_db)) -> CapsuleProvisionerRead:
    """Return the Capsule-specific view for a provisioner."""
    return _capsule_read_model(_load_provisioner_of_type(db, provisioner_id, "capsule"))


@provisioners_router.get("/{provisioner_id}/dynatrace", response_model=DynatraceProvisionerRead)
def get_dynatrace_provisioner(provisioner_id: int, db: Session = Depends(get_db)) -> DynatraceProvisionerRead:
    """Return the Dynatrace-specific view for a provisioner."""
    return _dynatrace_provisioner_read_model(_load_provisioner_of_type(db, provisioner_id, "dynatrace"))


@provisioners_router.patch("/{provisioner_id}/capsule", response_model=CapsuleProvisionerRead)
def update_capsule_provisioner(
    provisioner_id: int,
    payload: CapsuleProvisionerUpdate,
    db: Session = Depends(get_db),
) -> CapsuleProvisionerRead:
    """Patch a Capsule provisioner through its typed sub-route.

    Shared provisioner fields are updated directly, while the token stays
    inside encrypted `config` and is preserved when omitted.
    """
    provisioner = _load_provisioner_of_type(db, provisioner_id, "capsule")
    values = payload.model_dump(exclude_unset=True, exclude={"token"})
    if "platform_id" in values:
        _ensure_provisioner_platform_can_change(provisioner, values["platform_id"])
    apply_patch(provisioner, values)

    config = dict(provisioner.config)
    if payload.token is not None:
        config["token"] = payload.token
    provisioner.config = config

    commit_or_409(db, "provisioner name already exists for this platform")
    db.refresh(provisioner)
    return _capsule_read_model(provisioner)


@provisioners_router.patch("/{provisioner_id}/dynatrace", response_model=DynatraceProvisionerRead)
def update_dynatrace_provisioner(
    provisioner_id: int,
    payload: DynatraceProvisionerUpdate,
    db: Session = Depends(get_db),
) -> DynatraceProvisionerRead:
    """Patch a Dynatrace provisioner while keeping the secret hidden.

    Omitting `token` keeps the current secret, while a new `url` or `token`
    rewrites only the typed config values stored in `config`.
    """
    provisioner = _load_provisioner_of_type(db, provisioner_id, "dynatrace")
    values = payload.model_dump(exclude_unset=True, exclude={"url", "token"})
    if "platform_id" in values:
        _ensure_provisioner_platform_can_change(provisioner, values["platform_id"])
    apply_patch(provisioner, values)

    config = dict(provisioner.config)
    if payload.url is not None:
        config["url"] = str(payload.url)
    if payload.token is not None:
        config["token"] = payload.token
    provisioner.config = config

    commit_or_409(db, "provisioner name already exists for this platform")
    db.refresh(provisioner)
    return _dynatrace_provisioner_read_model(provisioner)


@provisioners_router.delete("/{provisioner_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provisioner(provisioner_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a provisioner and cascade its dependent relations."""
    provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
    db.delete(provisioner)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@provisioners_router.post("/{provisioner_id}/run", response_model=TaskEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_provisioner_run(provisioner_id: int, db: Session = Depends(get_db)) -> TaskEnqueueResponse:
    """Enqueue a manual provisioner run through Celery."""
    get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
    task = enqueue_celery_task(RUN_PROVISIONER_TASK, args=[provisioner_id])
    return TaskEnqueueResponse(task_id=task.id)


router.include_router(providers_router)
router.include_router(provisioners_router)
