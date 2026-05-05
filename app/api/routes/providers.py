"""Typed provider routes.

Generic endpoints expose provider metadata only. Provider-specific
configuration is managed through typed sub-routes so secrets remain hidden
from the public API surface.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404
from internal.contracts.http.resources import (
    DynatraceProviderCreate,
    DynatraceProviderRead,
    DynatraceProviderUpdate,
    PrometheusProviderCreate,
    PrometheusProviderRead,
    PrometheusProviderUpdate,
    ProviderRead,
    ProvisionerRead,
    Scope,
    TaskEnqueueResponse,
)
from internal.infra.db.models import MachineProvider, MachineProvisioner
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import RUN_PROVIDER_TASK


router = APIRouter(prefix="/providers", tags=["providers"])


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
) -> list[MachineProvisioner]:
    """Resolve attached provisioners and validate their platform ownership."""
    provisioners: list[MachineProvisioner] = []
    for provisioner_id in provisioner_ids:
        provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
        if provisioner.platform_id != platform_id:
            raise HTTPException(status_code=400, detail="provider and provisioners must belong to the same platform")
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


def _dynatrace_read_model(provider: MachineProvider) -> DynatraceProviderRead:
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
    provider = MachineProvider(
        platform_id=payload.platform_id,
        name=payload.name,
        type="prometheus",
        scope=payload.scope,
        config={"url": str(payload.url), "query": payload.query},
        enabled=payload.enabled,
    )
    db.add(provider)
    provider.provisioners = _load_provisioners_for_provider(db, payload.provisioner_ids, payload.platform_id)
    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _prometheus_read_model(_load_provider(db, provider.id))


@router.post("/dynatrace", response_model=DynatraceProviderRead, status_code=status.HTTP_201_CREATED)
def create_dynatrace_provider(
    payload: DynatraceProviderCreate,
    db: Session = Depends(get_db),
) -> DynatraceProviderRead:
    """Create a typed Dynatrace provider."""
    provider = MachineProvider(
        platform_id=payload.platform_id,
        name=payload.name,
        type="dynatrace",
        scope=payload.scope,
        config={"url": str(payload.url), "token": payload.token},
        enabled=payload.enabled,
    )
    db.add(provider)
    provider.provisioners = _load_provisioners_for_provider(db, payload.provisioner_ids, payload.platform_id)
    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _dynatrace_read_model(_load_provider(db, provider.id))


@router.get("", response_model=list[ProviderRead])
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
    return _dynatrace_read_model(_load_provider_of_type(db, provider_id, "dynatrace"))


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
    values = payload.model_dump(exclude_unset=True, exclude={"scope", "url", "query", "provisioner_ids"})
    target_platform_id = values.get("platform_id", provider.platform_id)

    if payload.scope is not None:
        provider.scope = payload.scope

    if payload.provisioner_ids is not None:
        provider.provisioners = _load_provisioners_for_provider(db, payload.provisioner_ids, target_platform_id)
    elif "platform_id" in values:
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
    values = payload.model_dump(exclude_unset=True, exclude={"scope", "url", "token", "provisioner_ids"})
    target_platform_id = values.get("platform_id", provider.platform_id)

    if payload.scope is not None:
        provider.scope = payload.scope

    if payload.provisioner_ids is not None:
        provider.provisioners = _load_provisioners_for_provider(db, payload.provisioner_ids, target_platform_id)
    elif "platform_id" in values:
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
    return _dynatrace_read_model(_load_provider(db, provider.id))


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a provider and its association rows."""
    provider = _load_provider(db, provider_id)
    db.delete(provider)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{provider_id}/provisioners", response_model=list[ProvisionerRead])
def list_provider_provisioners(provider_id: int, db: Session = Depends(get_db)) -> list[MachineProvisioner]:
    """List the provisioners currently attached to a provider."""
    provider = _load_provider(db, provider_id)
    return provider.provisioners


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


@router.post("/{provider_id}/run", response_model=TaskEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_provider_run(provider_id: int, db: Session = Depends(get_db)) -> TaskEnqueueResponse:
    """Enqueue a manual provider run when the provider is enabled."""
    provider = _load_provider(db, provider_id)
    if not provider.enabled:
        raise HTTPException(status_code=409, detail="provider is disabled")
    task = celery_app.send_task(RUN_PROVIDER_TASK, args=[provider_id])
    return TaskEnqueueResponse(task_id=task.id)
