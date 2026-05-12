"""FastMCP server exposing a read-only product API surface."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from app.mcp.core.product_api import ProductAPIProxy
from app.mcp.resources import register_resources
from app.mcp.config import get_settings
from app.mcp.tools import register_tools

SERVER_INSTRUCTIONS = """
Read-only gateway over the Metrics Collector product API.

Prefer the resources when you need browsable data and the tools when your client only works with tool calls.
This server intentionally exposes only applications, machines, and stored machine metrics.
Create, update, delete, sync, enable, disable, provider, provisioner, platform, and worker-task actions are out of scope.
""".strip()


@lifespan
async def mcp_lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    """Initialize and share the downstream HTTP client."""

    settings = get_settings()
    client = httpx.AsyncClient(
        base_url=settings.mcp_api_base_url.rstrip("/"),
        timeout=settings.mcp_api_timeout_seconds,
    )
    try:
        yield {"product_api_proxy": ProductAPIProxy(client)}
    finally:
        await client.aclose()


mcp = FastMCP(
    name="Metrics Collector MCP",
    instructions=SERVER_INSTRUCTIONS,
    lifespan=mcp_lifespan,
)
register_resources(mcp)
register_tools(mcp)

__all__ = ["mcp"]
