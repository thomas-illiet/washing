"""Shared cron validation rules."""

from croniter import croniter


INVALID_CRON_EXPRESSION_DETAIL = "cron must be a valid cron expression"


def validate_cron_expression(expression: str) -> str:
    """Return the expression when accepted by croniter, else raise ValueError."""
    if not croniter.is_valid(expression):
        raise ValueError(INVALID_CRON_EXPRESSION_DETAIL)
    return expression
