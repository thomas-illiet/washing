"""MCP tool for listing one machine's metric history."""

from typing import Any

from fastmcp import Context, FastMCP

from app.mcp.core.shared import ReadOnlyToolAnnotations
from app.mcp.core.shared import Limit, MetricType, Offset, OptionalPositiveInt, PositiveInt
from app.mcp.core.product_api import list_machine_metric_history as read_machine_metric_history


def register(mcp: FastMCP) -> None:
    """Register the list_machine_metric_history tool."""

    @mcp.tool(name="list_machine_metric_history", annotations=ReadOnlyToolAnnotations)
    async def list_machine_metric_history(
        ctx: Context,
        machine_id: PositiveInt,
        type: MetricType,
        provider_id: OptionalPositiveInt = None,
        start: str | None = None,
        end: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> dict[str, Any]:
        """List stored metrics for one machine and one metric type."""

        return await read_machine_metric_history(
            ctx,
            machine_id=machine_id,
            metric_type=type,
            provider_id=provider_id,
            start=start,
            end=end,
            offset=offset,
            limit=limit,
        )


__all__ = ["register"]
