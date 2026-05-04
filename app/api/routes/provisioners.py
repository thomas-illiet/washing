from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404
from internal.contracts.http.resources import ProvisionerCreate, ProvisionerRead, ProvisionerUpdate, TaskEnqueueResponse
from internal.infra.db.models import MachineProvisioner
from internal.infra.queue.celery import celery_app
from internal.infra.queue.task_names import RUN_PROVISIONER_TASK


router = APIRouter(prefix="/provisioners", tags=["provisioners"])


@router.post("", response_model=ProvisionerRead, status_code=status.HTTP_201_CREATED)
def create_provisioner(payload: ProvisionerCreate, db: Session = Depends(get_db)) -> MachineProvisioner:
    provisioner = MachineProvisioner(**payload.model_dump())
    db.add(provisioner)
    commit_or_409(db, "provisioner name already exists for this platform")
    db.refresh(provisioner)
    return provisioner


@router.get("", response_model=list[ProvisionerRead])
def list_provisioners(
    platform_id: int | None = None,
    enabled: bool | None = None,
    offset: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> list[MachineProvisioner]:
    query = db.query(MachineProvisioner)
    if platform_id is not None:
        query = query.filter(MachineProvisioner.platform_id == platform_id)
    if enabled is not None:
        query = query.filter(MachineProvisioner.enabled.is_(enabled))
    return query.offset(offset).limit(limit).all()


@router.get("/{provisioner_id}", response_model=ProvisionerRead)
def get_provisioner(provisioner_id: int, db: Session = Depends(get_db)) -> MachineProvisioner:
    return get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")


@router.patch("/{provisioner_id}", response_model=ProvisionerRead)
def update_provisioner(
    provisioner_id: int,
    payload: ProvisionerUpdate,
    db: Session = Depends(get_db),
) -> MachineProvisioner:
    provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
    apply_patch(provisioner, payload.model_dump(exclude_unset=True))
    commit_or_409(db, "provisioner name already exists for this platform")
    db.refresh(provisioner)
    return provisioner


@router.delete("/{provisioner_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provisioner(provisioner_id: int, db: Session = Depends(get_db)) -> Response:
    provisioner = get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
    db.delete(provisioner)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{provisioner_id}/run", response_model=TaskEnqueueResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_provisioner_run(provisioner_id: int, db: Session = Depends(get_db)) -> TaskEnqueueResponse:
    get_or_404(db, MachineProvisioner, provisioner_id, "provisioner not found")
    task = celery_app.send_task(RUN_PROVISIONER_TASK, args=[provisioner_id])
    return TaskEnqueueResponse(task_id=task.id)
