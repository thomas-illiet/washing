"""MCP tool for listing applications."""

from typing import Any

from fastmcp import Context, FastMCP

from app.mcp.core.shared import ReadOnlyToolAnnotations
from app.mcp.core.shared import Limit, Offset
from app.mcp.core.product_api import list_applications as read_applications


def register(mcp: FastMCP) -> None:
    """Register the list_applications tool."""

    @mcp.tool(name="list_applications", annotations=ReadOnlyToolAnnotations)
    async def list_applications(
        ctx: Context,
        name: str | None = None,
        environment: str | None = None,
        region: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> dict[str, Any]:
        """List applications with optional identity filters."""

        return await read_applications(
            ctx,
            name=name,
            environment=environment,
            region=region,
            offset=offset,
            limit=limit,
        )


__all__ = ["register"]
