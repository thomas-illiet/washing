"""Tests for Uvicorn access log filtering helpers."""

import logging

from internal.infra.observability.access_logging import SuppressAccessPathsFilter


def _access_record(path: str) -> logging.LogRecord:
    """Build one synthetic Uvicorn access log record for testing."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:12345", "GET", path, "1.1", 200),
        exc_info=None,
    )


def test_access_filter_hides_probe_paths() -> None:
    """Health and metrics requests should be filtered out from access logs."""
    access_filter = SuppressAccessPathsFilter({"/health", "/metrics"})

    assert access_filter.filter(_access_record("/health")) is False
    assert access_filter.filter(_access_record("/metrics?name[]=up")) is False


def test_access_filter_keeps_business_routes() -> None:
    """Normal API routes should still be logged."""
    access_filter = SuppressAccessPathsFilter({"/health", "/metrics"})

    assert access_filter.filter(_access_record("/v1/platforms")) is True
