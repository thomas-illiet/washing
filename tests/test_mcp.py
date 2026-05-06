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

from app.mcp.main import create_app
from app.mcp.settings import get_settings
from internal.infra.auth import clear_oidc_caches


APPLICATION_PAYLOAD = {
    "items": [
        {
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
    ],
    "offset": 0,
    "limit": 1,
    "total": 1,
}
MACHINES_PAYLOAD = {
    "items": [
        {
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
    ],
    "offset": 0,
    "limit": 100,
    "total": 1,
}
METRICS_PAYLOAD = {
    "items": [
        {
            "id": 8,
            "provider_id": 5,
            "machine_id": 42,
            "date": "2026-05-01",
            "value": 73,
        }
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
        monkeypatch.setenv("MCP_PRODUCT_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            result = asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "list_applications",
                    {"environment": "prod", "limit": 1},
                    authorization="Bearer forwarded-token",
                )
            )

    assert result == APPLICATION_PAYLOAD
    last_call = downstream.state.calls[-1]
    assert last_call["path"] == "/v1/applications"
    assert last_call["authorization"] == "Bearer forwarded-token"
    assert last_call["query"] == {"environment": "prod", "offset": "0", "limit": "1"}


def test_mcp_resource_forwards_authorization_and_maps_metric_query_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP resource reads should relay Authorization and map template parameters."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_PRODUCT_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            payload = asyncio.run(
                _read_http_resource(
                    f"{mcp_server.base_url}/mcp",
                    "metrics-collector://machine-metrics/cpu?machine_id=42&start=2026-05-01&end=2026-05-02&offset=1&limit=2",
                    authorization="Bearer resource-token",
                )
            )

    assert payload == METRICS_PAYLOAD
    last_call = downstream.state.calls[-1]
    assert last_call["path"] == "/v1/machines/metrics"
    assert last_call["authorization"] == "Bearer resource-token"
    assert last_call["query"] == {
        "type": "cpu",
        "machine_id": "42",
        "start": "2026-05-01",
        "end": "2026-05-02",
        "offset": "1",
        "limit": "2",
    }


def test_mcp_tool_omits_authorization_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Authorization header should be synthesized when the client omits it."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_PRODUCT_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            result = asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "list_machines",
                    {"application": "billing"},
                )
            )

    assert result == MACHINES_PAYLOAD
    last_call = downstream.state.calls[-1]
    assert last_call["path"] == "/v1/machines"
    assert last_call["authorization"] is None
    assert last_call["query"] == {"application": "billing", "offset": "0", "limit": "100"}


def test_mcp_tool_surfaces_readable_downstream_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Downstream 404 responses should become readable MCP tool errors."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_PRODUCT_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            with pytest.raises(Exception, match="product API returned 404 .* application not found"):
                asyncio.run(
                    _call_http_tool(
                        f"{mcp_server.base_url}/mcp",
                        "get_application",
                        {"application_id": 404},
                        authorization="Bearer missing",
                    )
                )


def test_mcp_tool_surfaces_unavailable_downstream_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connection failures should become readable MCP tool errors."""

    monkeypatch.setenv("MCP_PRODUCT_API_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MCP_PRODUCT_API_TIMEOUT_SECONDS", "0.2")
    with LiveServer(create_app()) as mcp_server:
        with pytest.raises(Exception, match="product API request failed for GET /v1/applications"):
            asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "list_applications",
                    {"limit": 1},
                    authorization="Bearer unavailable",
                )
            )


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
        return result.data


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

    @app.get("/v1/applications")
    async def list_applications() -> dict[str, object]:
        """Return a stable application payload."""

        return APPLICATION_PAYLOAD

    @app.get("/v1/applications/{application_id}")
    async def get_application(application_id: int):
        """Return one application or a controlled 404."""

        if application_id == 404:
            return JSONResponse(status_code=404, content={"detail": "application not found"})
        return APPLICATION_PAYLOAD["items"][0]

    @app.get("/v1/machines")
    async def list_machines() -> dict[str, object]:
        """Return a stable machine payload."""

        return MACHINES_PAYLOAD

    @app.get("/v1/machines/metrics")
    async def list_machine_metrics() -> dict[str, object]:
        """Return a stable machine-metrics payload."""

        return METRICS_PAYLOAD

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
