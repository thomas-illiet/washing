"""Tests for runtime settings validation."""

import pytest
from pydantic import ValidationError

from internal.infra.auth import OIDCSettings
from internal.infra.config.settings import Settings, get_settings
from internal.infra.security import decrypt_json_value, encrypt_json_value
from tests.constants import TEST_ENCRYPTION_KEY


def test_encryption_key_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """The application should fail fast when the encryption key is missing or invalid."""
    # Override any local .env value so the validation path is deterministic.
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_settings()

    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    get_settings.cache_clear()
    assert get_settings().database_encryption_key == TEST_ENCRYPTION_KEY


def test_app_env_defaults_to_prod_and_dev_sets_is_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    """Runtime settings should expose the selected application environment."""
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    settings = Settings(_env_file=None)
    assert settings.app_env == "prod"
    assert settings.is_dev is False

    monkeypatch.setenv("APP_ENV", "dev")
    settings = Settings(_env_file=None)
    assert settings.app_env == "dev"
    assert settings.is_dev is True


def test_oidc_settings_require_an_issuer_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """OIDC mode should fail fast when the issuer URL is missing."""
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.delenv("OIDC_ISSUER_URL", raising=False)

    with pytest.raises(ValidationError):
        OIDCSettings(_env_file=None)


def test_oidc_role_names_are_configurable_and_must_stay_distinct(monkeypatch: pytest.MonkeyPatch) -> None:
    """OIDC role names should be configurable, non-empty, and not collapsed to one value."""
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER_URL", "https://issuer.example/realms/demo")
    monkeypatch.setenv("OIDC_USER_ROLE_NAME", "viewer")
    monkeypatch.setenv("OIDC_ADMIN_ROLE_NAME", "operator")

    settings = OIDCSettings(_env_file=None)
    assert settings.oidc_user_role_name == "viewer"
    assert settings.oidc_admin_role_name == "operator"

    monkeypatch.setenv("OIDC_ADMIN_ROLE_NAME", "viewer")
    with pytest.raises(ValidationError):
        OIDCSettings(_env_file=None)


def test_task_execution_retention_days_must_stay_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retention days should reject zero or negative values."""
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("CELERY_TASK_EXECUTION_RETENTION_DAYS", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_machine_retention_days_must_stay_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Machine retention days should reject zero or negative values."""
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("MACHINE_RETENTION_DAYS", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_application_retention_days_must_stay_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Application retention days should reject zero or negative values."""
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("APPLICATION_RETENTION_DAYS", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_flavor_optimization_window_size_must_stay_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    """Optimization window size should reject zero or negative values."""
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_WINDOW_SIZE", "0")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_flavor_optimization_cpu_bounds_must_be_ordered(monkeypatch: pytest.MonkeyPatch) -> None:
    """CPU optimization bounds should reject inverted minimum and maximum values."""
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_MIN_CPU", "8")
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_MAX_CPU", "4")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_flavor_optimization_ram_bounds_require_gib_alignment(monkeypatch: pytest.MonkeyPatch) -> None:
    """RAM optimization bounds should stay aligned on GiB capacities."""
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_MIN_RAM_MB", "2500")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_database_schema_defaults_to_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app should default to the dedicated application schema."""
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.delenv("DATABASE_SCHEMA", raising=False)

    settings = Settings(_env_file=None)

    assert settings.database_schema == "app"


def test_database_schema_must_be_a_simple_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Schema names should stay safe to pass into connection settings."""
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("DATABASE_SCHEMA", "app-schema")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_encrypted_payloads_fail_closed_when_ciphertext_is_invalid() -> None:
    """Corrupted ciphertext should never be treated as plaintext JSON."""
    payload = encrypt_json_value({"token": "secret"})
    assert decrypt_json_value(payload) == {"token": "secret"}

    with pytest.raises(ValueError, match="invalid encrypted payload"):
        decrypt_json_value("{\"token\": \"plaintext\"}")
