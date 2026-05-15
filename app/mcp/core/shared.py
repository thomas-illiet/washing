"""Shared MCP parameter types."""

from typing import Annotated, Literal

from pydantic import Field

ReadOnlyResourceAnnotations = {"readOnlyHint": True, "idempotentHint": True}
ReadOnlyToolAnnotations = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}

ApplicationId = Annotated[
    int,
    Field(gt=0, description="Application id returned by application_list or application_search."),
]
MachineId = Annotated[int, Field(gt=0, description="Machine id returned by machine_list or machine_search.")]
Offset = Annotated[int, Field(ge=0, description="Zero-based offset for paginated results.")]
PageSize = Annotated[int, Field(ge=1, le=200, description="Number of results to return, from 1 to 200.")]
PositiveInt = Annotated[
    int,
    Field(gt=0, description="Positive integer identifier."),
]
OptionalPositiveInt = Annotated[
    int | None,
    Field(default=None, gt=0, description="Optional positive integer identifier."),
]
OptionalApplicationCode = Annotated[
    str | None,
    Field(default=None, description="Optional application code; the product API normalizes it to uppercase."),
]
OptionalDimension = Annotated[
    str | None,
    Field(default=None, description="Optional environment or region dimension; the product API normalizes it."),
]
OptionalExternalId = Annotated[
    str | None,
    Field(default=None, description="Optional provider-specific machine external id."),
]
OptionalHostname = Annotated[
    str | None,
    Field(default=None, description="Optional machine hostname; the product API normalizes it to uppercase."),
]
OptionalSearchQuery = Annotated[
    str | None,
    Field(default=None, description="Optional free-text search term."),
]
SearchQuery = Annotated[str, Field(description="Free-text search term.")]
StatsWindowDays = Annotated[
    Literal[7, 15, 30],
    Field(description="Rolling stats window in days. Supported values are 7, 15, and 30."),
]

__all__ = [
    "ApplicationId",
    "MachineId",
    "Offset",
    "OptionalApplicationCode",
    "OptionalDimension",
    "OptionalExternalId",
    "OptionalHostname",
    "OptionalPositiveInt",
    "OptionalSearchQuery",
    "PageSize",
    "PositiveInt",
    "ReadOnlyResourceAnnotations",
    "ReadOnlyToolAnnotations",
    "SearchQuery",
    "StatsWindowDays",
]
