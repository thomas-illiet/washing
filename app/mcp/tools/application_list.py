"""MCP tool for listing applications."""

from fastmcp import Context, FastMCP

from app.mcp.core.models import MCPEnvelope, MCPPaginatedData
from app.mcp.core.product_api import list_applications
from app.mcp.core.shared import Offset, OptionalDimension, OptionalPositiveInt, PageSize, ReadOnlyToolAnnotations
from app.mcp.core.envelope import envelope
from internal.contracts.http.resources import ApplicationRead


def register(mcp: FastMCP) -> None:
    """Register the application_list tool."""

    @mcp.tool(
        name="application_list",
        title="List Applications",
        annotations=ReadOnlyToolAnnotations,
        tags={"applications"},
    )
    async def application_list(
        ctx: Context,
        environment: OptionalDimension = None,
        region: OptionalDimension = None,
        platform_id: OptionalPositiveInt = None,
        offset: Offset = 0,
        page_size: PageSize = 25,
    ) -> MCPEnvelope[MCPPaginatedData[ApplicationRead]]:
        """List applications with explicit filters and pagination."""

        return await envelope(
            "Applications listed.",
            lambda: list_applications(
                ctx,
                environment=environment,
                region=region,
                platform_id=platform_id,
                offset=offset,
                limit=page_size,
            ),
            tool_name="application_list",
            paginated=True,
            data_model=MCPPaginatedData[ApplicationRead],
        )


__all__ = ["register"]
