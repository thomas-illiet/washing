"""Tests for shared cron validation rules."""

import pytest

from internal.domain.cron import INVALID_CRON_EXPRESSION_DETAIL, validate_cron_expression


def test_validate_cron_expression_accepts_croniter_supported_expression() -> None:
    """Valid cron expressions should be returned unchanged."""
    assert validate_cron_expression("*/5 * * * *") == "*/5 * * * *"


def test_validate_cron_expression_rejects_invalid_expression() -> None:
    """Invalid cron expressions should raise a stable error message."""
    with pytest.raises(ValueError, match=INVALID_CRON_EXPRESSION_DETAIL):
        validate_cron_expression("not-a-cron")
