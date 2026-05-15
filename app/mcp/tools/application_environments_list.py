"""MCP tool for listing application environments."""

from fastmcp import Context, FastMCP

from app.mcp.core.models import MCPEnvelope
from app.mcp.core.product_api import list_application_environments
from app.mcp.core.shared import OptionalDimension, OptionalPositiveInt, ReadOnlyToolAnnotations
from app.mcp.core.envelope import envelope
from internal.contracts.http.resources import ApplicationDimensionListRead


def register(mcp: FastMCP) -> None:
    """Register the application_environments_list tool."""

    @mcp.tool(
        name="application_environments_list",
        title="List Application Environments",
        annotations=ReadOnlyToolAnnotations,
        tags={"applications", "dimensions"},
    )
    async def application_environments_list(
        ctx: Context,
        region: OptionalDimension = None,
        platform_id: OptionalPositiveInt = None,
    ) -> MCPEnvelope[ApplicationDimensionListRead]:
        """List available application environments."""

        return await envelope(
            "Application environments listed.",
            lambda: list_application_environments(ctx, region=region, platform_id=platform_id),
            tool_name="application_environments_list",
            data_model=ApplicationDimensionListRead,
        )


__all__ = ["register"]
