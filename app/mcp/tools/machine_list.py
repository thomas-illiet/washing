"""MCP tool for listing machines."""

from fastmcp import Context, FastMCP

from app.mcp.core.models import MCPEnvelope, MCPPaginatedData
from app.mcp.core.product_api import list_machines
from app.mcp.core.shared import (
    Offset,
    OptionalApplicationCode,
    OptionalDimension,
    OptionalPositiveInt,
    PageSize,
    ReadOnlyToolAnnotations,
)
from app.mcp.core.envelope import envelope
from internal.contracts.http.resources import MachineRead


def register(mcp: FastMCP) -> None:
    """Register the machine_list tool."""

    @mcp.tool(
        name="machine_list",
        title="List Machines",
        annotations=ReadOnlyToolAnnotations,
        tags={"machines"},
    )
    async def machine_list(
        ctx: Context,
        application_id: OptionalPositiveInt = None,
        application_name: OptionalApplicationCode = None,
        environment: OptionalDimension = None,
        region: OptionalDimension = None,
        platform_id: OptionalPositiveInt = None,
        offset: Offset = 0,
        page_size: PageSize = 25,
    ) -> MCPEnvelope[MCPPaginatedData[MachineRead]]:
        """List machines with application and dimension filters."""

        return await envelope(
            "Machines listed.",
            lambda: list_machines(
                ctx,
                application_id=application_id,
                application_name=application_name,
                environment=environment,
                region=region,
                platform_id=platform_id,
                offset=offset,
                limit=page_size,
            ),
            tool_name="machine_list",
            paginated=True,
            data_model=MCPPaginatedData[MachineRead],
        )


__all__ = ["register"]
