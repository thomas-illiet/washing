"""FastMCP server exposing a read-only product API surface."""

from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from app.mcp.core.product_api import ProductAPIProxy
from app.mcp.resources import register_resources
from app.mcp.prompts import register_prompts
from app.mcp.config import get_settings
from app.mcp.tools import register_tools

SERVER_INSTRUCTIONS = """
Read-only discovery assistant for the Metrics Collector product API.

Use the discovery tools to help users find applications, machines, environments, regions, and current optimization recommendations without knowing internal ids.
Prefer get_application_overview and get_machine_context when answering operational questions.
Use search and fetch for ChatGPT/deep-research style retrieval.
Create, update, delete, sync, enable, disable, provider-secret, provisioner-secret, and worker-task actions are out of scope.
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
register_prompts(mcp)
register_tools(mcp)

__all__ = ["mcp"]
