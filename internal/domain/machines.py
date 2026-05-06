"""Machine-domain normalization helpers."""


def _normalize_optional(value: str | None, transform) -> str | None:
    """Normalize optional identifiers while preserving missing values."""
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    return transform(normalized)


def normalize_external_id(value: str | None) -> str | None:
    """Return the canonical external-id form used for machine matching."""
    return _normalize_optional(value, str.lower)


def normalize_hostname(value: str | None) -> str | None:
    """Return the canonical hostname form used for machine matching."""
    return _normalize_optional(value, str.upper)
