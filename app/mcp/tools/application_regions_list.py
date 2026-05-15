"""MCP tool for listing application regions."""

from fastmcp import Context, FastMCP

from app.mcp.core.models import MCPEnvelope
from app.mcp.core.product_api import list_application_regions
from app.mcp.core.shared import OptionalDimension, OptionalPositiveInt, ReadOnlyToolAnnotations
from app.mcp.core.envelope import envelope
from internal.contracts.http.resources import ApplicationDimensionListRead


def register(mcp: FastMCP) -> None:
    """Register the application_regions_list tool."""

    @mcp.tool(
        name="application_regions_list",
        title="List Application Regions",
        annotations=ReadOnlyToolAnnotations,
        tags={"applications", "dimensions"},
    )
    async def application_regions_list(
        ctx: Context,
        environment: OptionalDimension = None,
        platform_id: OptionalPositiveInt = None,
    ) -> MCPEnvelope[ApplicationDimensionListRead]:
        """List available application regions."""

        return await envelope(
            "Application regions listed.",
            lambda: list_application_regions(ctx, environment=environment, platform_id=platform_id),
            tool_name="application_regions_list",
            data_model=ApplicationDimensionListRead,
        )


__all__ = ["register"]
