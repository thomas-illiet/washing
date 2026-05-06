"""FastMCP server exposing a read-only product API surface."""

import json
from typing import Annotated, Any, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.server.lifespan import lifespan
from pydantic import Field

from app.mcp.product_api import ProductAPIProxy, proxy_get_json
from app.mcp.settings import get_settings


MetricType = Literal["cpu", "ram", "disk"]
Offset = Annotated[int, Field(ge=0)]
Limit = Annotated[int, Field(ge=1)]
PositiveInt = Annotated[int, Field(gt=0)]
OptionalPositiveInt = Annotated[int | None, Field(default=None, gt=0)]
ReadOnlyResourceAnnotations = {"readOnlyHint": True, "idempotentHint": True}
ReadOnlyToolAnnotations = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}
SERVER_INSTRUCTIONS = """
Read-only gateway over the Metrics Collector product API.

Prefer the resources when you need browsable data and the tools when your client only works with tool calls.
This server intentionally exposes only applications, machines, and stored machine metrics.
Create, update, delete, sync, enable, disable, provider, provisioner, platform, and worker-task actions are out of scope.
""".strip()


@lifespan
async def mcp_lifespan(_server: FastMCP) -> dict[str, Any]:
    """Initialize and share the downstream HTTP client."""

    settings = get_settings()
    client = httpx.AsyncClient(
        base_url=settings.mcp_product_api_base_url.rstrip("/"),
        timeout=settings.mcp_product_api_timeout_seconds,
    )
    try:
        yield {"product_api_proxy": ProductAPIProxy(client)}
    finally:
        await client.aclose()


mcp = FastMCP(
    name="Metrics Collector MCP",
    instructions=SERVER_INSTRUCTIONS,
    lifespan=mcp_lifespan,
)


async def _list_applications(
    ctx: Context,
    name: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Proxy the application collection endpoint."""

    return await proxy_get_json(
        ctx,
        "/v1/applications",
        {
            "name": name,
            "environment": environment,
            "region": region,
            "offset": offset,
            "limit": limit,
        },
    )


async def _get_application(ctx: Context, application_id: int) -> dict[str, Any]:
    """Proxy one application read endpoint."""

    return await proxy_get_json(ctx, f"/v1/applications/{application_id}")


async def _list_machines(
    ctx: Context,
    platform_id: int | None = None,
    application: str | None = None,
    source_provisioner_id: int | None = None,
    environment: str | None = None,
    region: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Proxy the machine collection endpoint."""

    return await proxy_get_json(
        ctx,
        "/v1/machines",
        {
            "platform_id": platform_id,
            "application": application,
            "source_provisioner_id": source_provisioner_id,
            "environment": environment,
            "region": region,
            "offset": offset,
            "limit": limit,
        },
    )


async def _get_machine(ctx: Context, machine_id: int) -> dict[str, Any]:
    """Proxy one machine read endpoint."""

    return await proxy_get_json(ctx, f"/v1/machines/{machine_id}")


async def _list_machine_metrics(
    ctx: Context,
    metric_type: MetricType,
    platform_id: int | None = None,
    provider_id: int | None = None,
    provisioner_id: int | None = None,
    machine_id: int | None = None,
    start: str | None = None,
    end: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Proxy the cross-machine metrics endpoint."""

    return await proxy_get_json(
        ctx,
        "/v1/machines/metrics",
        {
            "type": metric_type,
            "platform_id": platform_id,
            "provider_id": provider_id,
            "provisioner_id": provisioner_id,
            "machine_id": machine_id,
            "start": start,
            "end": end,
            "offset": offset,
            "limit": limit,
        },
    )


async def _list_machine_metric_history(
    ctx: Context,
    machine_id: int,
    metric_type: MetricType,
    provider_id: int | None = None,
    start: str | None = None,
    end: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Proxy the per-machine metrics history endpoint."""

    return await proxy_get_json(
        ctx,
        f"/v1/machines/{machine_id}/metrics",
        {
            "type": metric_type,
            "provider_id": provider_id,
            "start": start,
            "end": end,
            "offset": offset,
            "limit": limit,
        },
    )


def _resource_json(payload: dict[str, Any]) -> str:
    """Serialize a downstream JSON payload for a resource response."""

    return json.dumps(payload)


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

    payload = await _list_applications(ctx, name=name, environment=environment, region=region, offset=offset, limit=limit)
    return _resource_json(payload)


@mcp.resource(
    "metrics-collector://applications/{application_id}",
    mime_type="application/json",
    annotations=ReadOnlyResourceAnnotations,
)
async def application_resource(ctx: Context, application_id: PositiveInt) -> str:
    """Read one application by identifier."""

    payload = await _get_application(ctx, application_id)
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

    payload = await _list_machines(
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

    payload = await _get_machine(ctx, machine_id)
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

    payload = await _list_machine_metrics(
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

    payload = await _list_machine_metric_history(
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


@mcp.tool(name="list_applications", annotations=ReadOnlyToolAnnotations)
async def list_applications(
    ctx: Context,
    name: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    offset: Offset = 0,
    limit: Limit = 100,
) -> dict[str, Any]:
    """List applications with optional identity filters."""

    return await _list_applications(ctx, name=name, environment=environment, region=region, offset=offset, limit=limit)


@mcp.tool(name="get_application", annotations=ReadOnlyToolAnnotations)
async def get_application(ctx: Context, application_id: PositiveInt) -> dict[str, Any]:
    """Read one application by identifier."""

    return await _get_application(ctx, application_id)


@mcp.tool(name="list_machines", annotations=ReadOnlyToolAnnotations)
async def list_machines(
    ctx: Context,
    platform_id: OptionalPositiveInt = None,
    application: str | None = None,
    source_provisioner_id: OptionalPositiveInt = None,
    environment: str | None = None,
    region: str | None = None,
    offset: Offset = 0,
    limit: Limit = 100,
) -> dict[str, Any]:
    """List machines with optional platform and ownership filters."""

    return await _list_machines(
        ctx,
        platform_id=platform_id,
        application=application,
        source_provisioner_id=source_provisioner_id,
        environment=environment,
        region=region,
        offset=offset,
        limit=limit,
    )


@mcp.tool(name="get_machine", annotations=ReadOnlyToolAnnotations)
async def get_machine(ctx: Context, machine_id: PositiveInt) -> dict[str, Any]:
    """Read one machine by identifier."""

    return await _get_machine(ctx, machine_id)


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

    return await _list_machine_metrics(
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

    return await _list_machine_metric_history(
        ctx,
        machine_id=machine_id,
        metric_type=type,
        provider_id=provider_id,
        start=start,
        end=end,
        offset=offset,
        limit=limit,
    )


__all__ = ["mcp"]
