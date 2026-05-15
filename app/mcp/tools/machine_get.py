"""MCP tool for reading one machine."""

from typing import Any

from fastmcp import Context, FastMCP

from app.mcp.core.models import MCPEnvelope
from app.mcp.core.product_api import (
    get_machine,
    get_machine_current_optimization,
    get_machine_latest_metrics,
)
from app.mcp.core.shared import MachineId, ReadOnlyToolAnnotations
from app.mcp.core.envelope import envelope
from internal.contracts.http.resources import MachineDetailRead


def register(mcp: FastMCP) -> None:
    """Register the machine_get tool."""

    @mcp.tool(
        name="machine_get",
        title="Get Machine",
        annotations=ReadOnlyToolAnnotations,
        tags={"machines", "metrics", "optimizations"},
    )
    async def machine_get(ctx: Context, machine_id: MachineId) -> MCPEnvelope[MachineDetailRead]:
        """Get machine detail with latest metrics and current optimization."""

        async def load_machine_detail() -> dict[str, Any]:
            machine = await get_machine(ctx, machine_id)
            latest_metrics = await get_machine_latest_metrics(ctx, machine_id)
            current_optimization = await get_machine_current_optimization(ctx, machine_id)
            detail = MachineDetailRead.model_validate(
                {
                    "machine": machine,
                    "latest_metrics": latest_metrics,
                    "current_optimization": current_optimization,
                }
            )
            return detail.model_dump(mode="json")

        return await envelope(
            "Machine loaded.",
            load_machine_detail,
            tool_name="machine_get",
            data_model=MachineDetailRead,
        )


__all__ = ["register"]
