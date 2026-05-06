"""Helpers for filtering low-signal Uvicorn access logs."""

from __future__ import annotations

import logging
from collections.abc import Iterable


_ACCESS_FILTER_ATTR = "_metrics_collector_access_filter"


class SuppressAccessPathsFilter(logging.Filter):
    """Hide access log records for low-signal HTTP paths such as probes."""

    def __init__(self, hidden_paths: Iterable[str] | None = None) -> None:
        """Store the exact normalized paths that should not reach the console."""
        super().__init__()
        self.hidden_paths = {path for path in hidden_paths or () if path}

    def filter(self, record: logging.LogRecord) -> bool:
        """Return False when one Uvicorn access record targets a hidden path."""
        path = _record_request_path(record)
        return path not in self.hidden_paths


def configure_uvicorn_access_log_filter(hidden_paths: Iterable[str]) -> None:
    """Install or update the shared Uvicorn access log filter."""
    logger = logging.getLogger("uvicorn.access")
    normalized_paths = {path for path in hidden_paths if path}

    existing = getattr(logger, _ACCESS_FILTER_ATTR, None)
    if isinstance(existing, SuppressAccessPathsFilter):
        existing.hidden_paths.update(normalized_paths)
        return

    access_filter = SuppressAccessPathsFilter(normalized_paths)
    logger.addFilter(access_filter)
    setattr(logger, _ACCESS_FILTER_ATTR, access_filter)


def _record_request_path(record: logging.LogRecord) -> str | None:
    """Extract the request path from one Uvicorn access log record."""
    if isinstance(record.args, tuple) and len(record.args) >= 3:
        candidate = record.args[2]
        if isinstance(candidate, str):
            return candidate.split("?", 1)[0]
    return None
