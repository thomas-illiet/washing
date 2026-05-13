"""MCP-specific structured response models."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from internal.contracts.http.resources import MachineContextRead


class MCPModel(BaseModel):
    """Base model for structured MCP tool outputs."""

    model_config = ConfigDict(extra="forbid")


class SearchResult(MCPModel):
    """One ChatGPT-compatible search result."""

    id: str
    title: str
    url: str


class SearchResponse(MCPModel):
    """ChatGPT-compatible search response."""

    results: list[SearchResult]


class FetchResponse(MCPModel):
    """ChatGPT-compatible fetch response."""

    id: str
    title: str
    text: str
    url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MachineOptimizationExplanation(MCPModel):
    """Deterministic machine optimization explanation."""

    machine_id: int
    hostname: str
    status: str | None = None
    action: str | None = None
    summary: str
    context: MachineContextRead
