"""Helpers for encrypting and decrypting integration configuration."""

import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from internal.infra.config.settings import get_settings


@lru_cache
def _get_fernet() -> Fernet:
    """Create and cache the Fernet instance used for config encryption."""
    return Fernet(get_settings().integration_config_encryption_key.encode("utf-8"))


def encrypt_json_value(value: dict[str, Any]) -> str:
    """Serialize and encrypt a JSON-compatible dictionary."""
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _get_fernet().encrypt(payload).decode("utf-8")


def decrypt_json_value(value: Any) -> dict[str, Any]:
    """Decrypt a stored payload and return the decoded dictionary."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise TypeError(f"unsupported encrypted payload type: {type(value)!r}")

    try:
        decrypted = _get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        return json.loads(decrypted)
    except InvalidToken as exc:
        raise ValueError("invalid encrypted payload") from exc
