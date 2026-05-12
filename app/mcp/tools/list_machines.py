"""MCP tool for listing machines."""

from typing import Any

from fastmcp import Context, FastMCP

from app.mcp.core.shared import ReadOnlyToolAnnotations
from app.mcp.core.shared import Limit, Offset, OptionalPositiveInt
from app.mcp.core.product_api import list_machines as read_machines


def register(mcp: FastMCP) -> None:
    """Register the list_machines tool."""

    @mcp.tool(name="list_machines", annotations=ReadOnlyToolAnnotations)
    async def list_machines(
        ctx: Context,
        platform_id: OptionalPositiveInt = None,
        application: str | None = None,
        source_provisioner_id: OptionalPositiveInt = None,
        environment: str | None = None,
        region: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> dict[str, Any]:
        """List machines with optional platform and ownership filters."""

        return await read_machines(
            ctx,
            platform_id=platform_id,
            application=application,
            source_provisioner_id=source_provisioner_id,
            environment=environment,
            region=region,
            offset=offset,
            limit=limit,
        )


__all__ = ["register"]
