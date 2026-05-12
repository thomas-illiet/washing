"""MCP tool for reading one machine."""

from typing import Any

from fastmcp import Context, FastMCP

from app.mcp.core.shared import ReadOnlyToolAnnotations
from app.mcp.core.shared import PositiveInt
from app.mcp.core.product_api import get_machine as read_machine


def register(mcp: FastMCP) -> None:
    """Register the get_machine tool."""

    @mcp.tool(name="get_machine", annotations=ReadOnlyToolAnnotations)
    async def get_machine(ctx: Context, machine_id: PositiveInt) -> dict[str, Any]:
        """Read one machine by identifier."""

        return await read_machine(ctx, machine_id)


__all__ = ["register"]
