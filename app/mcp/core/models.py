"""MCP-specific structured response models."""

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class MCPModel(BaseModel):
    """Base model for structured MCP tool outputs."""

    model_config = ConfigDict(extra="forbid")


class MCPPagination(MCPModel):
    """Short pagination block used by MCP list tools."""

    cursor: str | None = None
    page_size: int
    total: int


ResourceT = TypeVar("ResourceT")
EnvelopeDataT = TypeVar("EnvelopeDataT")


class MCPPaginatedData(MCPModel, Generic[ResourceT]):
    """Paginated item block returned inside the common MCP envelope."""

    items: list[ResourceT]
    offset: int


class MCPEnvelope(MCPModel, Generic[EnvelopeDataT]):
    """Common MCP tool response envelope."""

    status: Literal["success", "failed"]
    message: str
    data: EnvelopeDataT | dict[str, Any] = Field(default_factory=dict)
    pagination: MCPPagination | None = None
    error: str | None = None
