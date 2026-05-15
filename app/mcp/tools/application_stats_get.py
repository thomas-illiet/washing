"""MCP tool for reading application stats."""

from fastmcp import Context, FastMCP

from app.mcp.core.models import MCPEnvelope
from app.mcp.core.product_api import get_application_stats
from app.mcp.core.shared import ApplicationId, ReadOnlyToolAnnotations, StatsWindowDays
from app.mcp.core.envelope import envelope
from internal.contracts.http.resources import ApplicationStatsRead


def register(mcp: FastMCP) -> None:
    """Register the application_stats_get tool."""

    @mcp.tool(
        name="application_stats_get",
        title="Get Application Stats",
        annotations=ReadOnlyToolAnnotations,
        tags={"applications", "metrics"},
    )
    async def application_stats_get(
        ctx: Context,
        application_id: ApplicationId,
        window_days: StatsWindowDays = 7,
    ) -> MCPEnvelope[ApplicationStatsRead]:
        """Get CPU, RAM, and disk allocation and usage over 7, 15, or 30 days."""

        return await envelope(
            "Application stats loaded.",
            lambda: get_application_stats(ctx, application_id, window_days),
            tool_name="application_stats_get",
            data_model=ApplicationStatsRead,
        )


__all__ = ["register"]
