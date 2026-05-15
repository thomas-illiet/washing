"""MCP tool for searching applications."""

from fastmcp import Context, FastMCP

from app.mcp.core.models import MCPEnvelope, MCPPaginatedData
from app.mcp.core.product_api import list_applications
from app.mcp.core.shared import (
    Offset,
    OptionalDimension,
    OptionalPositiveInt,
    PageSize,
    ReadOnlyToolAnnotations,
    SearchQuery,
)
from app.mcp.core.envelope import envelope
from internal.contracts.http.resources import ApplicationRead


def register(mcp: FastMCP) -> None:
    """Register the application_search tool."""

    @mcp.tool(
        name="application_search",
        title="Search Applications",
        annotations=ReadOnlyToolAnnotations,
        tags={"applications", "search"},
    )
    async def application_search(
        ctx: Context,
        query: SearchQuery,
        environment: OptionalDimension = None,
        region: OptionalDimension = None,
        platform_id: OptionalPositiveInt = None,
        offset: Offset = 0,
        page_size: PageSize = 25,
    ) -> MCPEnvelope[MCPPaginatedData[ApplicationRead]]:
        """Search applications by text plus optional filters."""

        return await envelope(
            "Applications searched.",
            lambda: list_applications(
                ctx,
                q=query,
                environment=environment,
                region=region,
                platform_id=platform_id,
                offset=offset,
                limit=page_size,
            ),
            tool_name="application_search",
            paginated=True,
            data_model=MCPPaginatedData[ApplicationRead],
        )


__all__ = ["register"]
