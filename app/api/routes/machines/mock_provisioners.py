"""Development-only mock provisioner routes."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404
from app.api.routes.machines.provisioners import (
    _ensure_provisioner_platform_can_change,
    _load_provisioner_of_type,
)
from internal.contracts.http.resources import (
    MockProvisionerCreate,
    MockProvisionerRead,
    MockProvisionerUpdate,
    ProvisionerRead,
)
from internal.infra.connectors.mock import DEFAULT_MOCK_PRESET, resolve_mock_preset_path
from internal.infra.db.models import MachineProvisioner, Platform


router = APIRouter(prefix="/machines/provisioners", tags=["Machine Provisioners"])


def _validate_mock_preset_or_400(preset: str) -> str:
    """Validate that the preset exists and can be loaded from the mock directory."""
    try:
        resolve_mock_preset_path(preset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return preset


def _mock_read_model(provisioner: MachineProvisioner) -> MockProvisionerRead:
    """Build the typed mock read model without exposing raw config storage."""
    return MockProvisionerRead(
        **ProvisionerRead.model_validate(provisioner).model_dump(),
        preset=str(provisioner.config.get("preset", DEFAULT_MOCK_PRESET)),
    )


@router.post("/mock", response_model=MockProvisionerRead, status_code=status.HTTP_201_CREATED)
def create_mock_provisioner(
    payload: MockProvisionerCreate,
    db: Session = Depends(get_db),
) -> MockProvisionerRead:
    """Create a development-only mock provisioner backed by a JSON preset."""
    get_or_404(db, Platform, payload.platform_id, "platform not found")
    preset = _validate_mock_preset_or_400(payload.preset)
    provisioner = MachineProvisioner(
        platform_id=payload.platform_id,
        name=payload.name,
        type="mock",
        config={"preset": preset},
        cron=payload.cron,
    )
    db.add(provisioner)
    commit_or_409(db, "provisioner name already exists for this platform")
    db.refresh(provisioner)
    return _mock_read_model(provisioner)


@router.get("/{provisioner_id}/mock", response_model=MockProvisionerRead)
def get_mock_provisioner(provisioner_id: int, db: Session = Depends(get_db)) -> MockProvisionerRead:
    """Return the typed view for a development-only mock provisioner."""
    return _mock_read_model(_load_provisioner_of_type(db, provisioner_id, "mock"))


@router.patch("/{provisioner_id}/mock", response_model=MockProvisionerRead)
def update_mock_provisioner(
    provisioner_id: int,
    payload: MockProvisionerUpdate,
    db: Session = Depends(get_db),
) -> MockProvisionerRead:
    """Patch a development-only mock provisioner and its preset."""
    provisioner = _load_provisioner_of_type(db, provisioner_id, "mock")
    values = payload.model_dump(exclude_unset=True, exclude={"preset"})
    if "platform_id" in values:
        get_or_404(db, Platform, values["platform_id"], "platform not found")
        _ensure_provisioner_platform_can_change(provisioner, values["platform_id"])
    apply_patch(provisioner, values)

    config = dict(provisioner.config)
    if payload.preset is not None:
        config["preset"] = _validate_mock_preset_or_400(payload.preset)
    provisioner.config = config

    commit_or_409(db, "provisioner name already exists for this platform")
    db.refresh(provisioner)
    return _mock_read_model(provisioner)
