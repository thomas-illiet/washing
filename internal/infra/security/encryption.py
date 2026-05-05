import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from internal.infra.config.settings import get_settings


@lru_cache
def _get_fernet() -> Fernet:
    return Fernet(get_settings().integration_config_encryption_key.encode("utf-8"))


def encrypt_json_value(value: dict[str, Any]) -> str:
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return _get_fernet().encrypt(payload).decode("utf-8")


def decrypt_json_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise TypeError(f"unsupported encrypted payload type: {type(value)!r}")

    try:
        decrypted = _get_fernet().decrypt(value.encode("utf-8")).decode("utf-8")
        return json.loads(decrypted)
    except InvalidToken:
        # Allow transitional plaintext JSON while migrating persisted rows.
        return json.loads(value)
