"""MCP tool for reading one application."""

from typing import Any

from fastmcp import Context, FastMCP

from app.mcp.core.shared import ReadOnlyToolAnnotations
from app.mcp.core.shared import PositiveInt
from app.mcp.core.product_api import get_application as read_application


def register(mcp: FastMCP) -> None:
    """Register the get_application tool."""

    @mcp.tool(name="get_application", annotations=ReadOnlyToolAnnotations)
    async def get_application(ctx: Context, application_id: PositiveInt) -> dict[str, Any]:
        """Read one application by identifier."""

        return await read_application(ctx, application_id)


__all__ = ["register"]
