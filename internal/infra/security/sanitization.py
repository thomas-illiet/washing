"""Helpers that sanitize operational errors and task payloads before exposure."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from json import JSONDecodeError
from typing import Any


DISABLED_ERROR = "disabled"
RESOURCE_NOT_FOUND_ERROR = "resource_not_found"
INVALID_CONFIGURATION_ERROR = "invalid_configuration"
CONNECTOR_UNAVAILABLE_ERROR = "connector_unavailable"
DISPATCH_FAILED_ERROR = "dispatch_failed"
UNEXPECTED_ERROR = "unexpected_error"

# Only expose counters and identifiers that remain useful without leaking internals.
SAFE_TASK_RESULT_KEYS = frozenset(
    {
        "application_id",
        "applications",
        "batch_size",
        "created",
        "deleted",
        "flavor_changes",
        "machine_id",
        "machines",
        "provider_id",
        "providers",
        "provisioners",
        "skipped",
        "status",
        "synced",
        "total",
        "updated",
    }
)


def sanitize_operational_error(value: BaseException | str | None) -> str | None:
    """Map internal exceptions to a bounded set of safe operational error codes."""
    if value is None:
        return None
    if isinstance(value, JSONDecodeError):
        return INVALID_CONFIGURATION_ERROR
    message = str(value).strip().lower()
    if not message:
        return UNEXPECTED_ERROR
    if "must be enabled" in message or "disabled" in message:
        return DISABLED_ERROR
    if message.endswith("not found") or " not found" in message:
        return RESOURCE_NOT_FOUND_ERROR
    if "unsupported metric collector type" in message or "unsupported machine provisioner type" in message:
        return CONNECTOR_UNAVAILABLE_ERROR
    if (
        "invalid mock" in message
        or "invalid config" in message
        or "invalid configuration" in message
        or "invalid encrypted payload" in message
    ):
        return INVALID_CONFIGURATION_ERROR
    if "enqueue" in message or "dispatch" in message or "publish" in message:
        return DISPATCH_FAILED_ERROR
    return UNEXPECTED_ERROR


def sanitize_task_result(value: object) -> dict[str, Any] | None:
    """Reduce task return values to a small, predictable JSON object."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        # Drop any key outside the public allowlist before the payload reaches the API.
        result = {
            str(key): _sanitize_json_value(item)
            for key, item in value.items()
            if str(key) in SAFE_TASK_RESULT_KEYS
        }
        return result or None
    return {"status": _sanitize_json_value(value)}


def _sanitize_json_value(value: object) -> Any:
    """Convert arbitrary task payload values to safe JSON-compatible primitives."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        # Nested mappings reuse the same allowlist to avoid secret-shaped subtrees.
        sanitized = {
            str(key): _sanitize_json_value(item)
            for key, item in value.items()
            if str(key) in SAFE_TASK_RESULT_KEYS
        }
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_sanitize_json_value(item) for item in value]
    return str(value)
