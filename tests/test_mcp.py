"""Integration tests for the FastMCP gateway."""

import asyncio
import json
import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from app.mcp.core import mcp as mcp_server
from app.mcp.main import create_app
from app.mcp.config import get_settings
from internal.infra.auth import clear_oidc_caches


PLATFORM_PAYLOAD = {
    "id": 7,
    "name": "Prod Platform",
    "description": None,
    "extra": {},
    "created_at": "2026-05-01T00:00:00",
    "updated_at": "2026-05-01T00:00:00",
}
APPLICATION_PAYLOAD = {
    "id": 1,
    "name": "BILLING",
    "environment": "PROD",
    "region": "EU-WEST-1",
    "sync_at": None,
    "sync_scheduled_at": None,
    "sync_error": None,
    "created_at": "2026-05-01T00:00:00",
    "updated_at": "2026-05-01T00:00:00",
}
APPLICATION_SUMMARY_PAYLOAD = {
    "application": APPLICATION_PAYLOAD,
    "machine_count": 1,
    "platform_ids": [7],
    "current_optimization_count": 1,
    "current_optimizations_by_status": {"ready": 1},
    "current_optimizations_by_action": {"scale_up": 1},
}
APPLICATIONS_DISCOVERY_PAYLOAD = {
    "items": [
        APPLICATION_SUMMARY_PAYLOAD
    ],
    "total": 1,
    "returned": 1,
    "truncated": False,
}
MACHINE_PAYLOAD = {
    "id": 42,
    "platform_id": 7,
    "application": "BILLING",
    "source_provisioner_id": 3,
    "external_id": "vm-42",
    "hostname": "BILLING-42",
    "region": "EU-WEST-1",
    "environment": "PROD",
    "cpu": 2.0,
    "ram_mb": 8192.0,
    "disk_mb": 122880.0,
    "extra": {},
    "created_at": "2026-05-01T00:00:00",
    "updated_at": "2026-05-01T00:00:00",
}
MACHINE_SEARCH_PAYLOAD = {
    "items": [
        MACHINE_PAYLOAD
    ],
    "total": 1,
    "returned": 1,
    "truncated": False,
}
METRIC_PAYLOAD = {
    "id": 8,
    "provider_id": 5,
    "machine_id": 42,
    "date": "2026-05-01",
    "value": 73,
}
OPTIMIZATION_PAYLOAD = {
    "id": 99,
    "machine_id": 42,
    "revision": 1,
    "is_current": True,
    "status": "ready",
    "action": "scale_up",
    "computed_at": "2026-05-02T00:00:00",
    "acknowledged_at": None,
    "acknowledged_by": None,
    "resources": {
        "cpu": {
            "status": "ok",
            "action": "scale_up",
            "current": 2.0,
            "recommended": 4.0,
            "unit": "cores",
            "utilization_percent": 91.0,
            "reason": "pressure_high",
        },
        "ram": {
            "status": "ok",
            "action": "keep",
            "current": 8192.0,
            "recommended": 8192.0,
            "unit": "mb",
            "utilization_percent": 50.0,
            "reason": "pressure_normal",
        },
        "disk": {
            "status": "ok",
            "action": "keep",
            "current": 122880.0,
            "recommended": 122880.0,
            "unit": "mb",
            "utilization_percent": 50.0,
            "reason": "pressure_normal",
        },
    },
    "created_at": "2026-05-02T00:00:00",
    "updated_at": "2026-05-02T00:00:00",
}
APPLICATION_OVERVIEW_PAYLOAD = {
    "application": APPLICATION_PAYLOAD,
    "machine_count": 1,
    "platform_ids": [7],
    "current_optimization_count": 1,
    "current_optimizations_by_status": {"ready": 1},
    "current_optimizations_by_action": {"scale_up": 1},
    "machines": MACHINE_SEARCH_PAYLOAD,
    "current_optimizations": {
        "items": [OPTIMIZATION_PAYLOAD],
        "total": 1,
        "returned": 1,
        "truncated": False,
    },
}
MACHINE_CONTEXT_PAYLOAD = {
    "machine": MACHINE_PAYLOAD,
    "platform": PLATFORM_PAYLOAD,
    "application": APPLICATION_PAYLOAD,
    "latest_metrics": {"cpu": METRIC_PAYLOAD, "ram": None, "disk": None},
    "current_optimization": OPTIMIZATION_PAYLOAD,
}
CURRENT_OPTIMIZATIONS_PAYLOAD = {
    "items": [
        {
            "optimization": OPTIMIZATION_PAYLOAD,
            "machine": MACHINE_PAYLOAD,
            "platform": PLATFORM_PAYLOAD,
            "application": APPLICATION_PAYLOAD,
        }
    ],
    "total": 1,
    "returned": 1,
    "truncated": False,
}
CATALOG_PAYLOAD = {
    "platforms": [PLATFORM_PAYLOAD],
    "environments": ["PROD"],
    "regions": ["EU-WEST-1"],
    "metric_types": ["cpu", "ram", "disk"],
    "optimization_statuses": ["ready", "partial", "error"],
    "optimization_actions": ["scale_up", "scale_down", "mixed", "keep", "insufficient_data", "unavailable"],
    "totals": {"platforms": 1, "applications": 1, "machines": 1, "current_optimizations": 1},
}
RECORD_PAYLOAD = {
    "id": "application:1",
    "type": "application",
    "title": "BILLING PROD EU-WEST-1",
    "text": "{\"application\":{\"name\":\"BILLING\"}}",
    "url": "metrics-collector://records/application:1",
    "metadata": {"application_id": 1, "name": "BILLING"},
}
METRICS_PAYLOAD = {
    "items": [
        METRIC_PAYLOAD
    ],
    "offset": 1,
    "limit": 2,
    "total": 1,
}


class LiveServer:
    """Run an ASGI app on a live local TCP port for HTTP client tests."""

    def __init__(self, app: FastAPI) -> None:
        """Configure the live server with a free local port."""

        self.app = app
        self.host = "127.0.0.1"
        self.port = _free_tcp_port()
        self._server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=self.host,
                port=self.port,
                log_level="error",
            )
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    @property
    def base_url(self) -> str:
        """Return the public URL of the live test server."""

        return f"http://{self.host}:{self.port}"

    def __enter__(self) -> "LiveServer":
        """Start the server and wait for readiness."""

        self._thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            if self._server.started:
                return self
            if not self._thread.is_alive():
                raise RuntimeError("test server stopped before startup completed")
            time.sleep(0.05)
        raise RuntimeError("timed out while waiting for the test server to start")

    def __exit__(self, *_exc_info: object) -> None:
        """Stop the live server cleanly."""

        self._server.should_exit = True
        self._thread.join(timeout=10)


@pytest.fixture(autouse=True)
def clear_mcp_settings_cache() -> Iterator[None]:
    """Keep MCP settings cache isolated between tests."""

    clear_oidc_caches()
    get_settings.cache_clear()
    yield
    clear_oidc_caches()
    get_settings.cache_clear()


def test_mcp_healthcheck() -> None:
    """The wrapper app should expose a simple health endpoint."""

    client = TestClient(create_app())
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_mcp_tool_forwards_authorization_and_preserves_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP MCP tool calls should relay Authorization and pass through JSON."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            result = asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "list_applications",
                    {"environment": "prod", "max_results": 1},
                    authorization="Bearer forwarded-token",
                )
            )

    assert result == APPLICATIONS_DISCOVERY_PAYLOAD
    last_call = downstream.state.calls[-1]
    assert last_call["path"] == "/v1/discovery/applications"
    assert last_call["authorization"] == "Bearer forwarded-token"
    assert last_call["query"] == {"environment": "prod", "max_results": "1"}


def test_mcp_resource_forwards_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP resource reads should relay Authorization and use discovery endpoints."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            payload = asyncio.run(
                _read_http_resource(
                    f"{mcp_server.base_url}/mcp",
                    "metrics-collector://catalog",
                    authorization="Bearer resource-token",
                )
            )

    assert payload == CATALOG_PAYLOAD
    last_call = downstream.state.calls[-1]
    assert last_call["path"] == "/v1/discovery/catalog"
    assert last_call["authorization"] == "Bearer resource-token"
    assert last_call["query"] == {}


def test_mcp_tool_omits_authorization_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Authorization header should be synthesized when the client omits it."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            result = asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "find_machine",
                    {"query": "billing"},
                )
            )

    assert result == MACHINE_SEARCH_PAYLOAD
    last_call = downstream.state.calls[-1]
    assert last_call["path"] == "/v1/discovery/machines/search"
    assert last_call["authorization"] is None
    assert last_call["query"] == {"q": "billing", "max_results": "25"}


def test_mcp_tool_surfaces_readable_downstream_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Downstream 404 responses should become readable MCP tool errors."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            with pytest.raises(Exception, match="product API returned 404 .* application not found"):
                asyncio.run(
                    _call_http_tool(
                        f"{mcp_server.base_url}/mcp",
                        "get_application_overview",
                        {"application_id": 404},
                        authorization="Bearer missing",
                    )
                )


def test_mcp_tool_surfaces_unavailable_downstream_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connection failures should become readable MCP tool errors."""

    monkeypatch.setenv("MCP_API_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MCP_API_TIMEOUT_SECONDS", "0.2")
    with LiveServer(create_app()) as mcp_server:
        with pytest.raises(Exception, match="product API request failed for GET /v1/discovery/applications"):
            asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "list_applications",
                    {"max_results": 1},
                    authorization="Bearer unavailable",
                )
            )


def test_mcp_surface_exposes_prompts_resources_and_hides_pagination() -> None:
    """The local MCP manifest should expose assistant-first components without pagination parameters."""

    async def inspect_surface():
        async with Client(mcp_server) as client:
            tools = await client.list_tools()
            prompts = await client.list_prompts()
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
        return tools, prompts, resources, templates

    tools, prompts, resources, templates = asyncio.run(inspect_surface())
    tool_names = {tool.name for tool in tools}
    assert {
        "discover_catalog",
        "list_applications",
        "find_application",
        "get_application_overview",
        "list_application_machines",
        "find_machine",
        "get_machine_context",
        "list_current_optimizations",
        "explain_machine_optimization",
        "search",
        "fetch",
    } <= tool_names
    assert not {"list_machine_metrics", "list_machine_metric_history", "list_machines"} & tool_names
    for tool in tools:
        assert "offset" not in tool.inputSchema.get("properties", {})
        assert "limit" not in tool.inputSchema.get("properties", {})
        assert tool.outputSchema is not None
    assert {prompt.name for prompt in prompts} == {
        "discover_application",
        "explain_application_optimizations",
        "investigate_machine_capacity",
    }
    assert {str(resource.uri) for resource in resources} == {
        "metrics-collector://catalog",
        "metrics-collector://optimizations/current",
    }
    assert {str(template.uriTemplate) for template in templates} == {
        "metrics-collector://applications/{application_id}/overview",
        "metrics-collector://machines/{machine_id}/context",
    }


def test_mcp_search_and_fetch_use_chatgpt_compatible_shapes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Search and fetch should match the ChatGPT-compatible MCP result shapes."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            search_result = asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "search",
                    {"query": "billing"},
                    authorization="Bearer search-token",
                )
            )
            fetch_result = asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "fetch",
                    {"id": "application:1"},
                    authorization="Bearer fetch-token",
                )
            )

    assert search_result["results"][0] == {
        "id": "application:1",
        "title": "Application BILLING in PROD/EU-WEST-1",
        "url": "metrics-collector://records/application:1",
    }
    assert {"id", "title", "url"} <= set(search_result["results"][1])
    assert fetch_result == {
        "id": "application:1",
        "title": "BILLING PROD EU-WEST-1",
        "text": "{\"application\":{\"name\":\"BILLING\"}}",
        "url": "metrics-collector://records/application:1",
        "metadata": {"application_id": 1, "name": "BILLING"},
    }


async def _call_http_tool(
    mcp_url: str,
    tool_name: str,
    arguments: dict[str, object],
    authorization: str | None = None,
) -> dict[str, object]:
    """Call one MCP tool over HTTP and return its structured data."""

    transport = StreamableHttpTransport(url=mcp_url, headers=_transport_headers(authorization))
    client = Client(transport)
    async with client:
        result = await client.call_tool(tool_name, arguments)
        return result.structured_content


async def _read_http_resource(mcp_url: str, uri: str, authorization: str | None = None) -> dict[str, object]:
    """Read one MCP resource over HTTP and decode its JSON payload."""

    transport = StreamableHttpTransport(url=mcp_url, headers=_transport_headers(authorization))
    client = Client(transport)
    async with client:
        content = await client.read_resource(uri)
    assert hasattr(content[0], "text")
    return json.loads(content[0].text)


def _build_downstream_app() -> FastAPI:
    """Create a tiny product API stub used by MCP integration tests."""

    app = FastAPI()
    app.state.calls = []

    @app.middleware("http")
    async def capture_request(request: Request, call_next):
        """Record the path, query string, and forwarded Authorization header."""

        app.state.calls.append(
            {
                "path": request.url.path,
                "query": dict(request.query_params),
                "authorization": request.headers.get("authorization"),
            }
        )
        return await call_next(request)

    @app.get("/v1/discovery/catalog")
    async def discovery_catalog() -> dict[str, object]:
        """Return a stable discovery catalog payload."""

        return CATALOG_PAYLOAD

    @app.get("/v1/discovery/applications")
    async def list_applications() -> dict[str, object]:
        """Return stable application discovery payload."""

        return APPLICATIONS_DISCOVERY_PAYLOAD

    @app.get("/v1/discovery/applications/{application_id}/overview")
    async def get_application_overview(application_id: int):
        """Return one application overview or a controlled 404."""

        if application_id == 404:
            return JSONResponse(status_code=404, content={"detail": "application not found"})
        return APPLICATION_OVERVIEW_PAYLOAD

    @app.get("/v1/discovery/machines/search")
    async def search_machines() -> dict[str, object]:
        """Return a stable machine search payload."""

        return MACHINE_SEARCH_PAYLOAD

    @app.get("/v1/discovery/machines/{machine_id}/context")
    async def get_machine_context(machine_id: int) -> dict[str, object]:
        """Return a stable machine context payload."""

        return MACHINE_CONTEXT_PAYLOAD

    @app.get("/v1/discovery/optimizations/current")
    async def current_optimizations() -> dict[str, object]:
        """Return stable current optimization recommendations."""

        return CURRENT_OPTIMIZATIONS_PAYLOAD

    @app.get("/v1/discovery/records/{record_id:path}")
    async def fetch_record(record_id: str) -> dict[str, object]:
        """Return a stable fetch record."""

        return RECORD_PAYLOAD

    return app


def _transport_headers(authorization: str | None) -> dict[str, str] | None:
    """Build optional HTTP headers for the MCP client transport."""

    if authorization is None:
        return None
    return {"Authorization": authorization}


def _free_tcp_port() -> int:
    """Reserve and release one ephemeral TCP port."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
