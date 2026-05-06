"""Tests for runtime settings validation."""

import pytest
from pydantic import ValidationError

from internal.infra.config.settings import Settings, get_settings
from tests.constants import TEST_ENCRYPTION_KEY


def test_encryption_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """The application should fail fast when the encryption key is missing or invalid."""
    # Override any local .env value so the validation path is deterministic.
    monkeypatch.setenv("INTEGRATION_CONFIG_ENCRYPTION_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_settings()

    monkeypatch.setenv("INTEGRATION_CONFIG_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    get_settings.cache_clear()
    assert get_settings().integration_config_encryption_key == TEST_ENCRYPTION_KEY


def test_app_env_defaults_to_prod_and_dev_sets_is_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runtime settings should expose the selected application environment."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("INTEGRATION_CONFIG_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    settings = Settings(_env_file=None)
    assert settings.app_env == "prod"
    assert settings.is_dev is False

    monkeypatch.setenv("APP_ENV", "dev")
    settings = Settings(_env_file=None)
    assert settings.app_env == "dev"
    assert settings.is_dev is True
