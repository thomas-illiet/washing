"""HTTP proxy helpers for the product API."""

from datetime import date
from typing import Any, Mapping
from urllib.parse import quote

import httpx
from fastmcp import Context
from fastmcp.server.dependencies import get_http_headers

from app.mcp.core.shared import MetricType


class ProductAPIProxy:
    """Thin read-only JSON client over the product API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Store the shared HTTP client."""

        self._client = client

    async def get_json(self, path: str, params: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None) -> dict[str, Any]:
        """Perform a GET request and decode a JSON object response."""

        cleaned_params = _clean_query_params(params or {})
        try:
            response = await self._client.get(path, params=cleaned_params, headers=dict(headers or {}))
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise RuntimeError(f"product API request timed out for GET {path}") from exc
        except httpx.HTTPStatusError as exc:
            detail = _response_detail(exc.response)
            raise RuntimeError(
                f"product API returned {exc.response.status_code} for GET {path}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"product API request failed for GET {path}: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"product API returned invalid JSON for GET {path}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"product API returned an unexpected payload for GET {path}")
        return payload


def get_product_api_proxy(ctx: Context) -> ProductAPIProxy:
    """Return the shared product API proxy from the server lifespan state."""

    proxy = ctx.lifespan_context.get("product_api_proxy")
    if not isinstance(proxy, ProductAPIProxy):
        raise RuntimeError("product API proxy is unavailable")
    return proxy


def forwarded_authorization_headers() -> dict[str, str]:
    """Forward only the incoming Authorization header, when present."""

    authorization = get_http_headers().get("authorization")
    if not authorization:
        return {}
    return {"Authorization": authorization}


async def proxy_get_json(ctx: Context, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Proxy a read-only GET request to the product API."""

    proxy = get_product_api_proxy(ctx)
    return await proxy.get_json(path, params=params, headers=forwarded_authorization_headers())


async def list_applications(
    ctx: Context,
    name: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Read the application collection endpoint."""

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


async def get_application(ctx: Context, application_id: int) -> dict[str, Any]:
    """Read one application endpoint."""

    return await proxy_get_json(ctx, f"/v1/applications/{application_id}")


async def list_machines(
    ctx: Context,
    platform_id: int | None = None,
    application: str | None = None,
    source_provisioner_id: int | None = None,
    environment: str | None = None,
    region: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Read the machine collection endpoint."""

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


async def get_machine(ctx: Context, machine_id: int) -> dict[str, Any]:
    """Read one machine endpoint."""

    return await proxy_get_json(ctx, f"/v1/machines/{machine_id}")


async def list_machine_metrics(
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
    """Read the cross-machine metrics endpoint."""

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


async def list_machine_metric_history(
    ctx: Context,
    machine_id: int,
    metric_type: MetricType,
    provider_id: int | None = None,
    start: str | None = None,
    end: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Read the per-machine metrics history endpoint."""

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


async def discovery_catalog(ctx: Context) -> dict[str, Any]:
    """Read the assistant discovery catalog endpoint."""

    return await proxy_get_json(ctx, "/v1/discovery/catalog")


async def discovery_applications(
    ctx: Context,
    name: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    platform_id: int | None = None,
    max_results: int = 25,
) -> dict[str, Any]:
    """Read assistant-friendly application summaries."""

    return await proxy_get_json(
        ctx,
        "/v1/discovery/applications",
        {
            "name": name,
            "environment": environment,
            "region": region,
            "platform_id": platform_id,
            "max_results": max_results,
        },
    )


async def discovery_application_overview(
    ctx: Context,
    application_id: int,
    max_machines: int = 25,
    max_optimizations: int = 25,
) -> dict[str, Any]:
    """Read the full assistant context for one application."""

    return await proxy_get_json(
        ctx,
        f"/v1/discovery/applications/{application_id}/overview",
        {
            "max_machines": max_machines,
            "max_optimizations": max_optimizations,
        },
    )


async def discovery_machine_search(
    ctx: Context,
    q: str | None = None,
    hostname: str | None = None,
    external_id: str | None = None,
    application: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    platform_id: int | None = None,
    max_results: int = 25,
) -> dict[str, Any]:
    """Search assistant-friendly machine inventory."""

    return await proxy_get_json(
        ctx,
        "/v1/discovery/machines/search",
        {
            "q": q,
            "hostname": hostname,
            "external_id": external_id,
            "application": application,
            "environment": environment,
            "region": region,
            "platform_id": platform_id,
            "max_results": max_results,
        },
    )


async def discovery_machine_context(ctx: Context, machine_id: int) -> dict[str, Any]:
    """Read the full assistant context for one machine."""

    return await proxy_get_json(ctx, f"/v1/discovery/machines/{machine_id}/context")


async def discovery_current_optimizations(
    ctx: Context,
    platform_id: int | None = None,
    application: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    status: str | None = None,
    action: str | None = None,
    max_results: int = 25,
) -> dict[str, Any]:
    """Read current assistant-friendly optimization recommendations."""

    return await proxy_get_json(
        ctx,
        "/v1/discovery/optimizations/current",
        {
            "platform_id": platform_id,
            "application": application,
            "environment": environment,
            "region": region,
            "status": status,
            "action": action,
            "max_results": max_results,
        },
    )


async def discovery_record(ctx: Context, record_id: str) -> dict[str, Any]:
    """Read one fetchable discovery record."""

    return await proxy_get_json(ctx, f"/v1/discovery/records/{quote(record_id, safe='')}")


def _clean_query_params(params: Mapping[str, Any]) -> dict[str, Any]:
    """Drop null values and serialize dates for HTTP query parameters."""

    cleaned: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, date):
            cleaned[key] = value.isoformat()
        else:
            cleaned[key] = value
    return cleaned


def _response_detail(response: httpx.Response) -> str:
    """Extract a readable error detail from a downstream response."""

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict) and "detail" in payload:
        detail = payload["detail"]
        if isinstance(detail, list):
            return "; ".join(str(item) for item in detail)
        return str(detail)
    if response.text.strip():
        return response.text.strip()
    return response.reason_phrase
