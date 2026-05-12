"""MCP tool for listing machine metrics."""

from typing import Any

from fastmcp import Context, FastMCP

from app.mcp.core.shared import ReadOnlyToolAnnotations
from app.mcp.core.shared import Limit, MetricType, Offset, OptionalPositiveInt
from app.mcp.core.product_api import list_machine_metrics as read_machine_metrics


def register(mcp: FastMCP) -> None:
    """Register the list_machine_metrics tool."""

    @mcp.tool(name="list_machine_metrics", annotations=ReadOnlyToolAnnotations)
    async def list_machine_metrics(
        ctx: Context,
        type: MetricType,
        platform_id: OptionalPositiveInt = None,
        provider_id: OptionalPositiveInt = None,
        provisioner_id: OptionalPositiveInt = None,
        machine_id: OptionalPositiveInt = None,
        start: str | None = None,
        end: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> dict[str, Any]:
        """List stored metrics across machines for one metric type."""

        return await read_machine_metrics(
            ctx,
            metric_type=type,
            platform_id=platform_id,
            provider_id=provider_id,
            provisioner_id=provisioner_id,
            machine_id=machine_id,
            start=start,
            end=end,
            offset=offset,
            limit=limit,
        )


__all__ = ["register"]
