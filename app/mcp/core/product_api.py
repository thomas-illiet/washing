"""HTTP proxy helpers for the product API."""

from datetime import date
from typing import Any, Mapping

import httpx
from fastmcp import Context
from fastmcp.server.dependencies import get_http_headers


class ProductAPIError(RuntimeError):
    """Public downstream API error safe to return in MCP tool envelopes."""


class ProductAPIProxy:
    """Thin read-only JSON client over the product API."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Store the shared HTTP client."""

        self._client = client

    async def get_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        """Perform a GET request and decode a JSON object response."""

        cleaned_params = _clean_query_params(params or {})
        try:
            response = await self._client.get(path, params=cleaned_params, headers=dict(headers or {}))
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProductAPIError(f"product API request timed out for GET {path}") from exc
        except httpx.HTTPStatusError as exc:
            detail = _response_detail(exc.response)
            raise ProductAPIError(
                f"product API returned {exc.response.status_code} for GET {path}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProductAPIError(f"product API request failed for GET {path}: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProductAPIError(f"product API returned invalid JSON for GET {path}") from exc

        if not isinstance(payload, dict):
            raise ProductAPIError(f"product API returned an unexpected payload for GET {path}")
        return payload

    async def get_optional_json(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """Perform a GET request and return None for downstream 404 responses."""

        cleaned_params = _clean_query_params(params or {})
        try:
            response = await self._client.get(path, params=cleaned_params, headers=dict(headers or {}))
            if response.status_code == 404:
                return None
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProductAPIError(f"product API request timed out for GET {path}") from exc
        except httpx.HTTPStatusError as exc:
            detail = _response_detail(exc.response)
            raise ProductAPIError(
                f"product API returned {exc.response.status_code} for GET {path}: {detail}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProductAPIError(f"product API request failed for GET {path}: {exc}") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProductAPIError(f"product API returned invalid JSON for GET {path}") from exc

        if not isinstance(payload, dict):
            raise ProductAPIError(f"product API returned an unexpected payload for GET {path}")
        return payload


def get_product_api_proxy(ctx: Context) -> ProductAPIProxy:
    """Return the shared product API proxy from the server lifespan state."""

    proxy = ctx.lifespan_context.get("product_api_proxy")
    if not isinstance(proxy, ProductAPIProxy):
        raise RuntimeError("product API proxy is unavailable")
    return proxy


def forwarded_authorization_headers() -> dict[str, str]:
    """Forward only the incoming Authorization header, when present."""

    authorization = get_http_headers(include={"authorization"}).get("authorization")
    if not authorization:
        return {}
    return {"Authorization": authorization}


async def proxy_get_json(ctx: Context, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Proxy a read-only GET request to the product API."""

    proxy = get_product_api_proxy(ctx)
    return await proxy.get_json(path, params=params, headers=forwarded_authorization_headers())


async def proxy_get_optional_json(
    ctx: Context,
    path: str,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Proxy a read-only GET request and return None for 404 responses."""

    proxy = get_product_api_proxy(ctx)
    return await proxy.get_optional_json(path, params=params, headers=forwarded_authorization_headers())


async def list_applications(
    ctx: Context,
    q: str | None = None,
    name: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    platform_id: int | None = None,
    offset: int = 0,
    limit: int = 25,
) -> dict[str, Any]:
    """Read the application collection endpoint."""

    return await proxy_get_json(
        ctx,
        "/v1/applications",
        {
            "q": q,
            "name": name,
            "environment": environment,
            "region": region,
            "platform_id": platform_id,
            "offset": offset,
            "limit": limit,
        },
    )


async def get_application(ctx: Context, application_id: int) -> dict[str, Any]:
    """Read one application endpoint."""

    return await proxy_get_json(ctx, f"/v1/applications/{application_id}")


async def list_application_regions(
    ctx: Context,
    environment: str | None = None,
    platform_id: int | None = None,
) -> dict[str, Any]:
    """Read available application regions."""

    return await proxy_get_json(
        ctx,
        "/v1/applications/regions",
        {
            "environment": environment,
            "platform_id": platform_id,
        },
    )


async def list_application_environments(
    ctx: Context,
    region: str | None = None,
    platform_id: int | None = None,
) -> dict[str, Any]:
    """Read available application environments."""

    return await proxy_get_json(
        ctx,
        "/v1/applications/environments",
        {
            "region": region,
            "platform_id": platform_id,
        },
    )


async def get_application_stats(ctx: Context, application_id: int, window_days: int) -> dict[str, Any]:
    """Read application capacity and usage stats."""

    return await proxy_get_json(
        ctx,
        f"/v1/applications/{application_id}/stats",
        {"window_days": window_days},
    )


async def get_application_optimizations_summary(ctx: Context, application_id: int) -> dict[str, Any]:
    """Read aggregated application optimization recommendations."""

    return await proxy_get_json(ctx, f"/v1/applications/{application_id}/optimizations/summary")


async def list_machines(
    ctx: Context,
    q: str | None = None,
    platform_id: int | None = None,
    application_id: int | None = None,
    application_name: str | None = None,
    application: str | None = None,
    source_provisioner_id: int | None = None,
    hostname: str | None = None,
    external_id: str | None = None,
    environment: str | None = None,
    region: str | None = None,
    offset: int = 0,
    limit: int = 25,
) -> dict[str, Any]:
    """Read the machine collection endpoint."""

    return await proxy_get_json(
        ctx,
        "/v1/machines",
        {
            "q": q,
            "platform_id": platform_id,
            "application_id": application_id,
            "application_name": application_name,
            "application": application,
            "source_provisioner_id": source_provisioner_id,
            "hostname": hostname,
            "external_id": external_id,
            "environment": environment,
            "region": region,
            "offset": offset,
            "limit": limit,
        },
    )


async def get_machine(ctx: Context, machine_id: int) -> dict[str, Any]:
    """Read one machine endpoint."""

    return await proxy_get_json(ctx, f"/v1/machines/{machine_id}")


async def get_machine_latest_metrics(ctx: Context, machine_id: int) -> dict[str, Any]:
    """Read the latest metrics for one machine."""

    return await proxy_get_json(ctx, f"/v1/machines/{machine_id}/metrics/latest")


async def get_machine_current_optimization(ctx: Context, machine_id: int) -> dict[str, Any] | None:
    """Read the current optimization for one machine, returning None when absent."""

    return await proxy_get_optional_json(ctx, f"/v1/machines/{machine_id}/optimizations")


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
