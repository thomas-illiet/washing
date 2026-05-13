"""MCP resource registrations."""

import json
from typing import Any

from fastmcp import Context, FastMCP

from app.mcp.core.product_api import (
    discovery_application_overview,
    discovery_catalog,
    discovery_current_optimizations,
    discovery_machine_context,
)
from app.mcp.core.shared import PositiveInt, ReadOnlyResourceAnnotations


def register_resources(mcp: FastMCP) -> None:
    """Register assistant-friendly read-only resources on the MCP server."""

    @mcp.resource(
        "metrics-collector://catalog",
        name="discovery_catalog",
        title="Discovery Catalog",
        description="Browsable catalog of platforms, environments, regions, metric types, and optimization vocabulary.",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
        tags={"discovery", "catalog"},
    )
    async def catalog_resource(ctx: Context) -> str:
        """Read the top-level discovery catalog."""

        return _resource_json(await discovery_catalog(ctx))

    @mcp.resource(
        "metrics-collector://applications/{application_id}/overview",
        name="application_overview",
        title="Application Overview",
        description="Browsable application context with machines and current optimization recommendations.",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
        tags={"applications", "optimizations"},
    )
    async def application_overview_resource(ctx: Context, application_id: PositiveInt) -> str:
        """Read the assistant overview for one application."""

        return _resource_json(
            await discovery_application_overview(
                ctx,
                application_id=application_id,
                max_machines=100,
                max_optimizations=100,
            )
        )

    @mcp.resource(
        "metrics-collector://machines/{machine_id}/context",
        name="machine_context",
        title="Machine Context",
        description="Browsable machine context with ownership, latest metrics, and current optimization.",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
        tags={"machines", "metrics", "optimizations"},
    )
    async def machine_context_resource(ctx: Context, machine_id: PositiveInt) -> str:
        """Read the assistant context for one machine."""

        return _resource_json(await discovery_machine_context(ctx, machine_id))

    @mcp.resource(
        "metrics-collector://optimizations/current",
        name="current_optimizations",
        title="Current Optimizations",
        description="Browsable bounded list of current optimization recommendations across machines.",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
        tags={"optimizations"},
    )
    async def current_optimizations_resource(ctx: Context) -> str:
        """Read current optimization recommendations."""

        return _resource_json(await discovery_current_optimizations(ctx, max_results=100))


def _resource_json(payload: dict[str, Any]) -> str:
    """Serialize a downstream JSON payload for a resource response."""

    return json.dumps(payload)


__all__ = ["register_resources"]
