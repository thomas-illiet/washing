"""Typed provisioner routes.

Generic endpoints expose provisioner metadata only. Typed sub-routes own the
configuration lifecycle so secrets never leak through the generic API.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404
from internal.contracts.http.resources import (
    CapsuleProvisionerCreate,
    CapsuleProvisionerRead,
    CapsuleProvisionerUpdate,
    DynatraceProvisionerCreate,
    DynatraceProvisionerRead,
    DynatraceProvisionerUpdate,
    ProvisionerRead,
    TaskEnqueueResponse,
)
from internal.infra.db.models import MachineProvisioner
from internal.infra.queue.enqueue import enqueue_celery_task
from internal.infra.queue.task_names import RUN_PROVISIONER_TASK


router = APIRouter(prefix="/provisioners", tags=["provisioners"])


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


def _dynatrace_read_model(provisioner: MachineProvisioner) -> DynatraceProvisionerRead:
    """Build the Dynatrace read model with visible URL and hidden token."""
    return DynatraceProvisionerRead(
        **ProvisionerRead.model_validate(provisioner).model_dump(),
        url=str(provisioner.config.get("url", "")),
        has_token=bool(provisioner.config.get("token")),
    )


@router.post("/capsule", response_model=CapsuleProvisionerRead, status_code=status.HTTP_201_CREATED)
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


@router.post("/dynatrace", response_model=DynatraceProvisionerRead, status_code=status.HTTP_201_CREATED)
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
    return _dynatrace_read_model(provisioner)


@router.get("", response_model=list[ProvisionerRead])
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


@router.get("/{provisioner_id}", response_model=ProvisionerRead)
def get_provisioner(provisioner_id: int, db: Session = Depends(get_db)) -> MachineProvisioner:
    """Return one provisioner without exposing its typed config."""
    return get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")


@router.get("/{provisioner_id}/capsule", response_model=CapsuleProvisionerRead)
def get_capsule_provisioner(provisioner_id: int, db: Session = Depends(get_db)) -> CapsuleProvisionerRead:
    """Return the Capsule-specific view for a provisioner."""
    return _capsule_read_model(_load_provisioner_of_type(db, provisioner_id, "capsule"))


@router.get("/{provisioner_id}/dynatrace", response_model=DynatraceProvisionerRead)
def get_dynatrace_provisioner(provisioner_id: int, db: Session = Depends(get_db)) -> DynatraceProvisionerRead:
    """Return the Dynatrace-specific view for a provisioner."""
    return _dynatrace_read_model(_load_provisioner_of_type(db, provisioner_id, "dynatrace"))


@router.patch("/{provisioner_id}/capsule", response_model=CapsuleProvisionerRead)
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


@router.patch("/{provisioner_id}/dynatrace", response_model=DynatraceProvisionerRead)
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
    return _dynatrace_read_model(provisioner)


@router.delete("/{provisioner_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provisioner(provisioner_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a provisioner and cascade its dependent relations."""
    provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
    db.delete(provisioner)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{provisioner_id}/run", response_model=TaskEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_provisioner_run(provisioner_id: int, db: Session = Depends(get_db)) -> TaskEnqueueResponse:
    """Enqueue a manual provisioner run through Celery."""
    get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
    task = enqueue_celery_task(RUN_PROVISIONER_TASK, args=[provisioner_id])
    return TaskEnqueueResponse(task_id=task.id)
