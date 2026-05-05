"""Tests for runtime settings validation."""

import pytest
from pydantic import ValidationError

from internal.infra.config.settings import get_settings
from tests.constants import TEST_ENCRYPTION_KEY


def test_encryption_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """The application should fail fast when the encryption key is missing."""
    monkeypatch.delenv("INTEGRATION_CONFIG_ENCRYPTION_KEY", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_settings()

    monkeypatch.setenv("INTEGRATION_CONFIG_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    get_settings.cache_clear()
    assert get_settings().integration_config_encryption_key == TEST_ENCRYPTION_KEY
