from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404
from internal.contracts.http.resources import ProviderCreate, ProviderRead, ProviderUpdate, ProvisionerRead, TaskEnqueueResponse
from internal.infra.db.models import MachineProvider, MachineProvisioner
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import RUN_PROVIDER_TASK


router = APIRouter(prefix="/providers", tags=["providers"])


def _load_provider(db: Session, provider_id: int) -> MachineProvider:
    provider = (
        db.query(MachineProvider)
        .options(selectinload(MachineProvider.provisioners))
        .filter(MachineProvider.id == provider_id)
        .one_or_none()
    )
    if provider is None:
        raise HTTPException(status_code=404, detail="provider not found")
    return provider


def _load_provisioner_for_provider(db: Session, provider: MachineProvider, provisioner_id: int) -> MachineProvisioner:
    provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
    if provisioner.platform_id != provider.platform_id:
        raise HTTPException(status_code=400, detail="provider and provisioner must belong to the same platform")
    return provisioner


@router.post("", response_model=ProviderRead, status_code=status.HTTP_201_CREATED)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db)) -> MachineProvider:
    values = payload.model_dump(exclude={"provisioner_ids"})
    provider = MachineProvider(**values)
    db.add(provider)

    for provisioner_id in payload.provisioner_ids:
        provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
        if provisioner.platform_id != provider.platform_id:
            raise HTTPException(status_code=400, detail="provider and provisioners must belong to the same platform")
        provider.provisioners.append(provisioner)

    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _load_provider(db, provider.id)


@router.get("", response_model=list[ProviderRead])
def list_providers(
    platform_id: int | None = None,
    metric_type_id: int | None = None,
    enabled: bool | None = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[MachineProvider]:
    query = db.query(MachineProvider).options(selectinload(MachineProvider.provisioners))
    if platform_id is not None:
        query = query.filter(MachineProvider.platform_id == platform_id)
    if metric_type_id is not None:
        query = query.filter(MachineProvider.metric_type_id == metric_type_id)
    if enabled is not None:
        query = query.filter(MachineProvider.enabled.is_(enabled))
    return query.offset(offset).limit(limit).all()


@router.get("/{provider_id}", response_model=ProviderRead)
def get_provider(provider_id: int, db: Session = Depends(get_db)) -> MachineProvider:
    return _load_provider(db, provider_id)


@router.patch("/{provider_id}", response_model=ProviderRead)
def update_provider(provider_id: int, payload: ProviderUpdate, db: Session = Depends(get_db)) -> MachineProvider:
    provider = _load_provider(db, provider_id)
    apply_patch(provider, payload.model_dump(exclude_unset=True))
    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _load_provider(db, provider.id)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: int, db: Session = Depends(get_db)) -> Response:
    provider = _load_provider(db, provider_id)
    db.delete(provider)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{provider_id}/provisioners", response_model=list[ProvisionerRead])
def list_provider_provisioners(provider_id: int, db: Session = Depends(get_db)) -> list[MachineProvisioner]:
    provider = _load_provider(db, provider_id)
    return provider.provisioners


@router.post("/{provider_id}/provisioners/{provisioner_id}", response_model=ProviderRead)
def attach_provider_provisioner(
    provider_id: int,
    provisioner_id: int,
    db: Session = Depends(get_db),
) -> MachineProvider:
    provider = _load_provider(db, provider_id)
    provisioner = _load_provisioner_for_provider(db, provider, provisioner_id)
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
    provider = _load_provider(db, provider_id)
    provisioner = _load_provisioner_for_provider(db, provider, provisioner_id)
    if provisioner in provider.provisioners:
        provider.provisioners.remove(provisioner)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{provider_id}/run", response_model=TaskEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_provider_run(provider_id: int, db: Session = Depends(get_db)) -> TaskEnqueueResponse:
    get_or_404(db, MachineProvider, provider_id, "provider not found")
    task = celery_app.send_task(RUN_PROVIDER_TASK, args=[provider_id])
    return TaskEnqueueResponse(task_id=task.id)
