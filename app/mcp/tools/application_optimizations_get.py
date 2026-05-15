"""MCP tool for reading application optimization summary."""

from fastmcp import Context, FastMCP

from app.mcp.core.models import MCPEnvelope
from app.mcp.core.product_api import get_application_optimizations_summary
from app.mcp.core.shared import ApplicationId, ReadOnlyToolAnnotations
from app.mcp.core.envelope import envelope
from internal.contracts.http.resources import ApplicationOptimizationSummaryRead


def register(mcp: FastMCP) -> None:
    """Register the application_optimizations_get tool."""

    @mcp.tool(
        name="application_optimizations_get",
        title="Get Application Optimizations",
        annotations=ReadOnlyToolAnnotations,
        tags={"applications", "optimizations"},
    )
    async def application_optimizations_get(
        ctx: Context,
        application_id: ApplicationId,
    ) -> MCPEnvelope[ApplicationOptimizationSummaryRead]:
        """Get aggregated CPU, RAM, and disk optimization recommendations for an application."""

        return await envelope(
            "Application optimizations loaded.",
            lambda: get_application_optimizations_summary(ctx, application_id),
            tool_name="application_optimizations_get",
            data_model=ApplicationOptimizationSummaryRead,
        )


__all__ = ["register"]
