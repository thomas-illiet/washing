"""MCP tool for searching machines."""

from fastmcp import Context, FastMCP

from app.mcp.core.models import MCPEnvelope, MCPPaginatedData
from app.mcp.core.product_api import list_machines
from app.mcp.core.shared import (
    Offset,
    OptionalApplicationCode,
    OptionalDimension,
    OptionalExternalId,
    OptionalHostname,
    OptionalPositiveInt,
    OptionalSearchQuery,
    PageSize,
    ReadOnlyToolAnnotations,
)
from app.mcp.core.envelope import envelope
from internal.contracts.http.resources import MachineRead


def register(mcp: FastMCP) -> None:
    """Register the machine_search tool."""

    @mcp.tool(
        name="machine_search",
        title="Search Machines",
        annotations=ReadOnlyToolAnnotations,
        tags={"machines", "search"},
    )
    async def machine_search(
        ctx: Context,
        query: OptionalSearchQuery = None,
        hostname: OptionalHostname = None,
        external_id: OptionalExternalId = None,
        application: OptionalApplicationCode = None,
        environment: OptionalDimension = None,
        region: OptionalDimension = None,
        platform_id: OptionalPositiveInt = None,
        offset: Offset = 0,
        page_size: PageSize = 25,
    ) -> MCPEnvelope[MCPPaginatedData[MachineRead]]:
        """Search machines by text, hostname, external id, application, or dimension."""

        return await envelope(
            "Machines searched.",
            lambda: list_machines(
                ctx,
                q=query,
                hostname=hostname,
                external_id=external_id,
                application_name=application,
                environment=environment,
                region=region,
                platform_id=platform_id,
                offset=offset,
                limit=page_size,
            ),
            tool_name="machine_search",
            paginated=True,
            data_model=MCPPaginatedData[MachineRead],
        )


__all__ = ["register"]
