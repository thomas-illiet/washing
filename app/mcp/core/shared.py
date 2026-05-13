"""Shared MCP parameter types."""

from typing import Annotated, Literal

from pydantic import Field

ReadOnlyResourceAnnotations = {"readOnlyHint": True, "idempotentHint": True}
ReadOnlyToolAnnotations = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}

MetricType = Literal["cpu", "ram", "disk"]
Offset = Annotated[int, Field(ge=0)]
Limit = Annotated[int, Field(ge=1)]
DiscoveryLimit = Annotated[int, Field(ge=1, le=100)]
PositiveInt = Annotated[int, Field(gt=0)]
OptionalPositiveInt = Annotated[int | None, Field(default=None, gt=0)]

__all__ = [
    "DiscoveryLimit",
    "Limit",
    "MetricType",
    "Offset",
    "OptionalPositiveInt",
    "PositiveInt",
    "ReadOnlyResourceAnnotations",
    "ReadOnlyToolAnnotations",
]
