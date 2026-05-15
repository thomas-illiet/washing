"""FastMCP server exposing a read-only product API surface."""

from collections.abc import AsyncIterator
import os
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

from app.mcp.core.product_api import ProductAPIProxy
from app.mcp.config import get_settings
from app.mcp.prompts import register_prompts
from app.mcp.resources import register_resources
from app.mcp.tools import register_tools

SERVER_INSTRUCTIONS = """
Read-only chat assistant for the Metrics Collector product API.

Use the application and machine tools to help users consult inventory, environments, regions,
stats, and current optimization recommendations.
Create, update, delete, sync, enable, disable, provider-secret, provisioner-secret, and
worker-task actions are out of scope.
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


def _server_version() -> str:
    """Return the installed project version advertised to MCP clients."""
    try:
        return version("metrics-collector")
    except PackageNotFoundError:
        return "0.1.0"


def _mcp_mask_error_details() -> bool:
    """Read the startup-time MCP error detail masking flag."""
    value = os.getenv("MCP_MASK_ERROR_DETAILS", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


mcp = FastMCP(
    name="Metrics Collector MCP",
    instructions=SERVER_INSTRUCTIONS,
    version=_server_version(),
    lifespan=mcp_lifespan,
    strict_input_validation=True,
    on_duplicate="error",
    mask_error_details=_mcp_mask_error_details(),
)
register_resources(mcp)
register_prompts(mcp)
register_tools(mcp)

__all__ = ["mcp"]
