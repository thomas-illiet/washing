"""Application-domain normalization helpers."""


def _normalize_optional(value: str | None, transform) -> str | None:
    """Normalize optional identifiers while preserving missing values."""
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None

    return transform(normalized)


def normalize_application_code(value: str | None) -> str | None:
    """Return the canonical application code."""
    return _normalize_optional(value, str.upper)


def normalize_dimension(value: str | None) -> str | None:
    """Return the canonical dimension form used for region and environment."""
    return _normalize_optional(value, str.upper)


def coalesce_dimension(value: str | None, default: str = "UNKNOWN") -> str:
    """Return a non-empty canonical dimension value."""
    return normalize_dimension(value) or default
