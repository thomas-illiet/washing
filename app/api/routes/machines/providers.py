"""Machine provider routes."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, selectinload

from app.api.deps import PaginationParams, get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404, paginate_query
from internal.contracts.http.resources import (
    DynatraceProviderCreate,
    DynatraceProviderRead,
    DynatraceProviderUpdate,
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
    PROVISIONER_PROVIDER_SCOPE_CONFLICT_DETAIL,
    MachineProvider,
    MachineProviderProvisioner,
    MachineProvisioner,
    Platform,
    find_provider_scope_conflict,
)
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import DISPATCH_ENABLED_PROVIDER_SYNCS_TASK


router = APIRouter(prefix="/machines/providers", tags=["Machine Providers"])
ENABLED_PROVIDER_SYNC_REQUIRED_DETAIL = "at least one enabled provider is required before syncing machine metrics"


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
    provider_scope: str,
    provider_id: int | None = None,
) -> list[MachineProvisioner]:
    """Resolve attached provisioners and validate their platform ownership."""
    provisioners: list[MachineProvisioner] = []
    for provisioner_id in provisioner_ids:
        provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
        if provisioner.platform_id != platform_id:
            raise HTTPException(status_code=400, detail="provider and provisioners must belong to the same platform")
        if find_provider_scope_conflict(provisioner, provider_scope, provider_id=provider_id) is not None:
            raise HTTPException(status_code=409, detail=PROVISIONER_PROVIDER_SCOPE_CONFLICT_DETAIL)
        provisioners.append(provisioner)
    return provisioners


def _ensure_provider_platform_matches_provisioners(provider: MachineProvider, platform_id: int) -> None:
    """Prevent moving a provider to a platform that mismatches its provisioners."""
    for provisioner in provider.provisioners:
        if provisioner.platform_id != platform_id:
            raise HTTPException(status_code=400, detail="provider and provisioners must belong to the same platform")


def _ensure_provider_scope_matches_provisioners(provider: MachineProvider, scope: str) -> None:
    """Prevent changing a provider scope to one already attached on its provisioners."""
    for provisioner in provider.provisioners:
        if find_provider_scope_conflict(provisioner, scope, provider_id=provider.id) is not None:
            raise HTTPException(status_code=409, detail=PROVISIONER_PROVIDER_SCOPE_CONFLICT_DETAIL)


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


@router.post("/prometheus", response_model=PrometheusProviderRead, status_code=status.HTTP_201_CREATED)
def create_prometheus_provider(
    payload: PrometheusProviderCreate,
    db: Session = Depends(get_db),
) -> PrometheusProviderRead:
    """Create a typed Prometheus provider."""
    get_or_404(db, Platform, payload.platform_id, "platform not found")
    provisioners = _load_provisioners_for_provider(
        db,
        payload.provisioner_ids,
        payload.platform_id,
        provider_scope=payload.scope,
    )
    provider = MachineProvider(
        platform_id=payload.platform_id,
        name=payload.name,
        type="prometheus",
        scope=payload.scope,
        config={"url": str(payload.url), "query": payload.query},
        provisioners=provisioners,
    )
    db.add(provider)
    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _prometheus_read_model(_load_provider(db, provider.id))


@router.post("/dynatrace", response_model=DynatraceProviderRead, status_code=status.HTTP_201_CREATED)
def create_dynatrace_provider(
    payload: DynatraceProviderCreate,
    db: Session = Depends(get_db),
) -> DynatraceProviderRead:
    """Create a typed Dynatrace provider."""
    get_or_404(db, Platform, payload.platform_id, "platform not found")
    provisioners = _load_provisioners_for_provider(
        db,
        payload.provisioner_ids,
        payload.platform_id,
        provider_scope=payload.scope,
    )
    provider = MachineProvider(
        platform_id=payload.platform_id,
        name=payload.name,
        type="dynatrace",
        scope=payload.scope,
        config={"url": str(payload.url), "token": payload.token},
        provisioners=provisioners,
    )
    db.add(provider)
    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _dynatrace_provider_read_model(_load_provider(db, provider.id))


@router.get("", response_model=PaginatedResponse[ProviderRead])
def list_providers(
    platform_id: int | None = None,
    scope: Scope | None = None,
    enabled: bool | None = None,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ProviderRead]:
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
    return paginate_query(query, ProviderRead, pagination, MachineProvider.name.asc(), MachineProvider.id.asc())


@router.post("/sync", response_model=TaskEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_provider_sync(db: Session = Depends(get_db)) -> TaskEnqueueResponse:
    """Enqueue the global machine-metrics sync across enabled providers."""
    has_enabled_provider = (
        db.query(MachineProvider.id)
        .filter(MachineProvider.enabled.is_(True))
        .order_by(MachineProvider.id.asc())
        .first()
    )
    if has_enabled_provider is None:
        raise HTTPException(status_code=409, detail=ENABLED_PROVIDER_SYNC_REQUIRED_DETAIL)

    task = enqueue_celery_task(DISPATCH_ENABLED_PROVIDER_SYNCS_TASK)
    return TaskEnqueueResponse(task_id=task.id)


@router.get("/{provider_id}", response_model=ProviderRead)
def get_provider(provider_id: int, db: Session = Depends(get_db)) -> MachineProvider:
    """Return a provider through the generic public representation."""
    return _load_provider(db, provider_id)


@router.get("/{provider_id}/prometheus", response_model=PrometheusProviderRead)
def get_prometheus_provider(provider_id: int, db: Session = Depends(get_db)) -> PrometheusProviderRead:
    """Return the Prometheus-specific configuration view for one provider."""
    return _prometheus_read_model(_load_provider_of_type(db, provider_id, "prometheus"))


@router.get("/{provider_id}/dynatrace", response_model=DynatraceProviderRead)
def get_dynatrace_provider(provider_id: int, db: Session = Depends(get_db)) -> DynatraceProviderRead:
    """Return the Dynatrace-specific configuration view for one provider."""
    return _dynatrace_provider_read_model(_load_provider_of_type(db, provider_id, "dynatrace"))


@router.post("/{provider_id}/enable", response_model=ProviderRead)
def enable_provider(provider_id: int, db: Session = Depends(get_db)) -> MachineProvider:
    """Enable one provider through an idempotent action endpoint."""
    provider = _load_provider(db, provider_id)
    provider.enabled = True
    db.commit()
    return _load_provider(db, provider_id)


@router.post("/{provider_id}/disable", response_model=ProviderRead)
def disable_provider(provider_id: int, db: Session = Depends(get_db)) -> MachineProvider:
    """Disable one provider through an idempotent action endpoint."""
    provider = _load_provider(db, provider_id)
    provider.enabled = False
    db.commit()
    return _load_provider(db, provider_id)


@router.patch("/{provider_id}/prometheus", response_model=PrometheusProviderRead)
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
        _ensure_provider_scope_matches_provisioners(provider, payload.scope)
        provider.scope = payload.scope

    if "platform_id" in values:
        get_or_404(db, Platform, target_platform_id, "platform not found")
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


@router.patch("/{provider_id}/dynatrace", response_model=DynatraceProviderRead)
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
        _ensure_provider_scope_matches_provisioners(provider, payload.scope)
        provider.scope = payload.scope

    if "platform_id" in values:
        get_or_404(db, Platform, target_platform_id, "platform not found")
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


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a provider and its association rows."""
    provider = _load_provider(db, provider_id)
    db.delete(provider)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{provider_id}/provisioners", response_model=PaginatedResponse[ProvisionerRead])
def list_provider_provisioners(
    provider_id: int,
    pagination: PaginationParams = Depends(PaginationParams),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ProvisionerRead]:
    """List the provisioners currently attached to a provider."""
    get_or_404(db, MachineProvider, provider_id, "provider not found")
    query = (
        db.query(MachineProvisioner)
        .join(
            MachineProviderProvisioner,
            MachineProviderProvisioner.provisioner_id == MachineProvisioner.id,
        )
        .filter(MachineProviderProvisioner.provider_id == provider_id)
    )
    return paginate_query(
        query,
        ProvisionerRead,
        pagination,
        MachineProvisioner.name.asc(),
        MachineProvisioner.id.asc(),
    )


@router.post("/{provider_id}/provisioners/{provisioner_id}", response_model=ProviderRead)
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
        if find_provider_scope_conflict(provisioner, provider.scope, provider_id=provider.id) is not None:
            raise HTTPException(status_code=409, detail=PROVISIONER_PROVIDER_SCOPE_CONFLICT_DETAIL)
        provider.provisioners.append(provisioner)
    commit_or_409(db, "provider/provisioner association already exists")
    return _load_provider(db, provider_id)


@router.delete("/{provider_id}/provisioners/{provisioner_id}", status_code=status.HTTP_204_NO_CONTENT)
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
