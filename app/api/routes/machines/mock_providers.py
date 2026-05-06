"""Development-only mock provider routes."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.routes.common import apply_patch, commit_or_409, get_or_404
from app.api.routes.machines.providers import (
    _ensure_provider_platform_matches_provisioners,
    _ensure_provider_scope_matches_provisioners,
    _load_provider_of_type,
)
from internal.contracts.http.resources import MockProviderCreate, MockProviderRead, MockProviderUpdate
from internal.infra.db.models import MachineProvider, Platform


router = APIRouter(prefix="/machines/providers", tags=["Machine Providers"])


def _mock_provider_read_model(provider: MachineProvider) -> MockProviderRead:
    """Build the typed mock read model without exposing the raw config blob."""
    return MockProviderRead.model_validate(provider)


@router.post("/mock", response_model=MockProviderRead, status_code=status.HTTP_201_CREATED)
def create_mock_provider(
    payload: MockProviderCreate,
    db: Session = Depends(get_db),
) -> MockProviderRead:
    """Create a development-only mock metric provider with random samples."""
    get_or_404(db, Platform, payload.platform_id, "platform not found")
    provider = MachineProvider(
        platform_id=payload.platform_id,
        name=payload.name,
        type="mock_metric",
        scope=payload.scope,
        config={},
    )
    db.add(provider)
    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _mock_provider_read_model(_load_provider_of_type(db, provider.id, "mock_metric"))


@router.get("/{provider_id}/mock", response_model=MockProviderRead)
def get_mock_provider(provider_id: int, db: Session = Depends(get_db)) -> MockProviderRead:
    """Return the typed view for a development-only mock metric provider."""
    return _mock_provider_read_model(_load_provider_of_type(db, provider_id, "mock_metric"))


@router.patch("/{provider_id}/mock", response_model=MockProviderRead)
def update_mock_provider(
    provider_id: int,
    payload: MockProviderUpdate,
    db: Session = Depends(get_db),
) -> MockProviderRead:
    """Patch a development-only mock metric provider."""
    provider = _load_provider_of_type(db, provider_id, "mock_metric")
    values = payload.model_dump(exclude_unset=True, exclude={"scope"})
    target_platform_id = values.get("platform_id", provider.platform_id)

    if payload.scope is not None:
        _ensure_provider_scope_matches_provisioners(provider, payload.scope)
        provider.scope = payload.scope

    if "platform_id" in values:
        get_or_404(db, Platform, target_platform_id, "platform not found")
        _ensure_provider_platform_matches_provisioners(provider, target_platform_id)

    apply_patch(provider, values)

    commit_or_409(db, "provider name already exists for this platform")
    db.refresh(provider)
    return _mock_provider_read_model(_load_provider_of_type(db, provider.id, "mock_metric"))
