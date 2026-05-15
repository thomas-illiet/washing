"""MCP tool for reading one application."""

from fastmcp import Context, FastMCP

from app.mcp.core.models import MCPEnvelope
from app.mcp.core.product_api import get_application
from app.mcp.core.shared import ApplicationId, ReadOnlyToolAnnotations
from app.mcp.core.envelope import envelope
from internal.contracts.http.resources import ApplicationRead


def register(mcp: FastMCP) -> None:
    """Register the application_get tool."""

    @mcp.tool(
        name="application_get",
        title="Get Application",
        annotations=ReadOnlyToolAnnotations,
        tags={"applications"},
    )
    async def application_get(ctx: Context, application_id: ApplicationId) -> MCPEnvelope[ApplicationRead]:
        """Get a short application detail by id."""

        return await envelope(
            "Application loaded.",
            lambda: get_application(ctx, application_id),
            tool_name="application_get",
            data_model=ApplicationRead,
        )


__all__ = ["register"]
