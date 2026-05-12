"""MCP resource registrations."""

import json
from typing import Any

from fastmcp import Context, FastMCP

from app.mcp.core.shared import ReadOnlyResourceAnnotations
from app.mcp.core.shared import Limit, MetricType, Offset, OptionalPositiveInt, PositiveInt
from app.mcp.core.product_api import (
    get_application,
    get_machine,
    list_applications,
    list_machine_metric_history,
    list_machine_metrics,
    list_machines,
)


def register_resources(mcp: FastMCP) -> None:
    """Register read-only resources on the MCP server."""

    @mcp.resource(
        "metrics-collector://applications{?name,environment,region,offset,limit}",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
    )
    async def applications_resource(
        ctx: Context,
        name: str | None = None,
        environment: str | None = None,
        region: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> str:
        """List applications with optional filters."""

        payload = await list_applications(
            ctx,
            name=name,
            environment=environment,
            region=region,
            offset=offset,
            limit=limit,
        )
        return _resource_json(payload)

    @mcp.resource(
        "metrics-collector://applications/{application_id}",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
    )
    async def application_resource(ctx: Context, application_id: PositiveInt) -> str:
        """Read one application by identifier."""

        payload = await get_application(ctx, application_id)
        return _resource_json(payload)

    @mcp.resource(
        "metrics-collector://machines{?platform_id,application,source_provisioner_id,environment,region,offset,limit}",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
    )
    async def machines_resource(
        ctx: Context,
        platform_id: OptionalPositiveInt = None,
        application: str | None = None,
        source_provisioner_id: OptionalPositiveInt = None,
        environment: str | None = None,
        region: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> str:
        """List machines with optional filters."""

        payload = await list_machines(
            ctx,
            platform_id=platform_id,
            application=application,
            source_provisioner_id=source_provisioner_id,
            environment=environment,
            region=region,
            offset=offset,
            limit=limit,
        )
        return _resource_json(payload)

    @mcp.resource(
        "metrics-collector://machines/{machine_id}",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
    )
    async def machine_resource(ctx: Context, machine_id: PositiveInt) -> str:
        """Read one machine by identifier."""

        payload = await get_machine(ctx, machine_id)
        return _resource_json(payload)

    @mcp.resource(
        "metrics-collector://machine-metrics/{type}{?platform_id,provider_id,provisioner_id,machine_id,start,end,offset,limit}",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
    )
    async def machine_metrics_resource(
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
    ) -> str:
        """List stored metrics across machines for one metric type."""

        payload = await list_machine_metrics(
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
        return _resource_json(payload)

    @mcp.resource(
        "metrics-collector://machines/{machine_id}/metrics/{type}{?provider_id,start,end,offset,limit}",
        mime_type="application/json",
        annotations=ReadOnlyResourceAnnotations,
    )
    async def machine_metric_history_resource(
        ctx: Context,
        machine_id: PositiveInt,
        type: MetricType,
        provider_id: OptionalPositiveInt = None,
        start: str | None = None,
        end: str | None = None,
        offset: Offset = 0,
        limit: Limit = 100,
    ) -> str:
        """List stored metrics for one machine and one metric type."""

        payload = await list_machine_metric_history(
            ctx,
            machine_id=machine_id,
            metric_type=type,
            provider_id=provider_id,
            start=start,
            end=end,
            offset=offset,
            limit=limit,
        )
        return _resource_json(payload)


def _resource_json(payload: dict[str, Any]) -> str:
    """Serialize a downstream JSON payload for a resource response."""

    return json.dumps(payload)


__all__ = ["register_resources"]
