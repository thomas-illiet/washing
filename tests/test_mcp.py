"""Integration tests for the FastMCP gateway."""

import asyncio
import json
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from prometheus_client import generate_latest

from app.mcp.config import get_settings
from app.mcp.core import mcp as mcp_server
from app.mcp.main import create_app
from internal.infra.auth import clear_oidc_caches


PROJECT_ROOT = Path(__file__).resolve().parents[1]

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
APPLICATION_LIST_PAYLOAD = {
    "items": [APPLICATION_PAYLOAD],
    "offset": 0,
    "limit": 25,
    "total": 1,
}
APPLICATION_DIMENSIONS_PAYLOAD = {"items": ["PROD"], "total": 1}
APPLICATION_REGIONS_PAYLOAD = {"items": ["EU-WEST-1"], "total": 1}
APPLICATION_STATS_PAYLOAD = {
    "application": APPLICATION_PAYLOAD,
    "window_days": 7,
    "start_date": "2026-04-25",
    "end_date": "2026-05-01",
    "machine_count": 1,
    "resources": {
        "cpu": {
            "allocated": 2.0,
            "allocated_unit": "cores",
            "average_usage_percent": 73.0,
            "peak_usage_percent": 91.0,
            "sample_count": 2,
        },
        "ram": {
            "allocated": 8192.0,
            "allocated_unit": "mb",
            "average_usage_percent": 50.0,
            "peak_usage_percent": 55.0,
            "sample_count": 2,
        },
        "disk": {
            "allocated": 122880.0,
            "allocated_unit": "mb",
            "average_usage_percent": 40.0,
            "peak_usage_percent": 45.0,
            "sample_count": 2,
        },
    },
}
APPLICATION_OPTIMIZATIONS_PAYLOAD = {
    "application": APPLICATION_PAYLOAD,
    "machine_count": 1,
    "optimization_count": 1,
    "recommendations_by_status": {"ready": 1},
    "recommendations_by_action": {"scale_up": 1},
    "resources": {
        "cpu": {
            "unit": "cores",
            "current_total": 2.0,
            "recommended_total": 4.0,
            "delta": 2.0,
            "reclaimable_capacity": 0.0,
            "additional_capacity": 2.0,
            "recommendations_by_status": {"ok": 1},
            "recommendations_by_action": {"scale_up": 1},
            "average_utilization_percent": 91.0,
            "reasons": ["pressure_high"],
        },
        "ram": {
            "unit": "mb",
            "current_total": 8192.0,
            "recommended_total": 8192.0,
            "delta": 0.0,
            "reclaimable_capacity": 0.0,
            "additional_capacity": 0.0,
            "recommendations_by_status": {"ok": 1},
            "recommendations_by_action": {"keep": 1},
            "average_utilization_percent": 50.0,
            "reasons": ["pressure_normal"],
        },
        "disk": {
            "unit": "mb",
            "current_total": 122880.0,
            "recommended_total": 122880.0,
            "delta": 0.0,
            "reclaimable_capacity": 0.0,
            "additional_capacity": 0.0,
            "recommendations_by_status": {"ok": 1},
            "recommendations_by_action": {"keep": 1},
            "average_utilization_percent": 50.0,
            "reasons": ["pressure_normal"],
        },
    },
    "confidence": "high",
    "confidence_score": 0.9,
    "justification": "All current recommendations are ready.",
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
MACHINE_LIST_PAYLOAD = {
    "items": [MACHINE_PAYLOAD],
    "offset": 0,
    "limit": 25,
    "total": 1,
}
METRIC_PAYLOAD = {
    "id": 8,
    "provider_id": 5,
    "machine_id": 42,
    "date": "2026-05-01",
    "value": 73,
}
LATEST_METRICS_PAYLOAD = {"cpu": METRIC_PAYLOAD, "ram": None, "disk": None}
OPTIMIZATION_PAYLOAD = {
    "id": 99,
    "machine_id": 42,
    "status": "ready",
    "action": "scale_up",
    "computed_at": "2026-05-02T00:00:00",
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


def test_mcp_tool_forwards_authorization_and_wraps_paginated_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP MCP tool calls should relay Authorization and return the common envelope."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            result = asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "application_list",
                    {"environment": "prod", "page_size": 1},
                    authorization="Bearer forwarded-token",
                )
            )

    assert result == {
        "status": "success",
        "message": "Applications listed.",
        "data": {"items": [APPLICATION_PAYLOAD], "offset": 0},
        "pagination": {"cursor": None, "page_size": 1, "total": 1},
        "error": None,
    }
    last_call = downstream.state.calls[-1]
    assert last_call["path"] == "/v1/applications"
    assert last_call["authorization"] == "Bearer forwarded-token"
    assert last_call["query"] == {"environment": "prod", "offset": "0", "limit": "1"}


def test_mcp_tool_omits_authorization_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Authorization header should be synthesized when the client omits it."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            result = asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "machine_search",
                    {"query": "billing"},
                )
            )

    assert result["status"] == "success"
    assert result["data"]["items"] == [MACHINE_PAYLOAD]
    last_call = downstream.state.calls[-1]
    assert last_call["path"] == "/v1/machines"
    assert last_call["authorization"] is None
    assert last_call["query"] == {"q": "billing", "offset": "0", "limit": "25"}


def test_mcp_tool_surfaces_readable_downstream_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Downstream HTTP errors should become readable failed envelopes."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            result = asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "application_get",
                    {"application_id": 404},
                    authorization="Bearer missing",
                )
            )

    assert result["status"] == "failed"
    assert result["data"] == {}
    assert result["pagination"] is None
    assert "product API returned 404" in result["error"]
    assert "application not found" in result["error"]


def test_mcp_tool_surfaces_unavailable_downstream_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connection failures should become readable failed envelopes."""

    monkeypatch.setenv("MCP_API_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("MCP_API_TIMEOUT_SECONDS", "0.2")
    with LiveServer(create_app()) as mcp_server:
        result = asyncio.run(
            _call_http_tool(
                f"{mcp_server.base_url}/mcp",
                "application_list",
                {"page_size": 1},
                authorization="Bearer unavailable",
            )
        )

    assert result["status"] == "failed"
    assert "product API request failed for GET /v1/applications" in result["error"]


def test_mcp_tool_masks_unexpected_internal_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unexpected internal failures should not leak validation details to the MCP caller."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            result = asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "application_get",
                    {"application_id": 500},
                    authorization="Bearer invalid-payload",
                )
            )

    assert result["status"] == "failed"
    assert result["error"] == "tool execution failed"
    assert "Field required" not in result["error"]
    assert "Traceback" not in result["error"]


def test_mcp_surface_exposes_chat_first_tools_resources_and_prompts() -> None:
    """The local MCP manifest should expose the chat-first read-only surface."""

    async def inspect_surface():
        async with Client(mcp_server) as client:
            tools = await client.list_tools()
            prompts = await client.list_prompts()
            resources = await client.list_resources()
            templates = await client.list_resource_templates()
        return tools, prompts, resources, templates

    tools, prompts, resources, templates = asyncio.run(inspect_surface())
    tool_names = {tool.name for tool in tools}
    assert tool_names == {
        "application_list",
        "application_search",
        "application_get",
        "application_regions_list",
        "application_environments_list",
        "machine_list",
        "machine_search",
        "machine_get",
        "application_stats_get",
        "application_optimizations_get",
    }
    assert not {
        "discover_catalog",
        "get_application_overview",
        "list_application_machines",
        "list_current_optimizations",
        "explain_machine_optimization",
        "search",
        "fetch",
        "application_sync_start",
        "application_sync_status",
        "application_sync_wait",
        "application_sync_cancel",
    } & tool_names
    for tool in tools:
        assert tool.outputSchema is not None
    assert {
        str(resource.uri)
        for resource in resources
    } == {
        "metrics-collector://mcp/catalog",
        "metrics-collector://optimizations/reason-codes",
    }
    assert {prompt.name for prompt in prompts} == {
        "application_capacity_review",
        "machine_optimization_explanation",
        "inventory_scope_discovery",
    }
    assert templates == []

    application_list_tool = next(tool for tool in tools if tool.name == "application_list")
    assert application_list_tool.inputSchema["properties"]["environment"]["description"]
    assert "Public representation of an application." in json.dumps(application_list_tool.outputSchema)


def test_mcp_resources_and_prompts_are_readable() -> None:
    """Resources and prompts should provide reusable client guidance."""

    async def read_guidance():
        async with Client(mcp_server) as client:
            catalog_content = await client.read_resource("metrics-collector://mcp/catalog")
            reasons_content = await client.read_resource("metrics-collector://optimizations/reason-codes")
            prompt = await client.get_prompt(
                "application_capacity_review",
                {"application_id": 1, "window_days": 7},
            )
        return catalog_content, reasons_content, prompt

    catalog_content, reasons_content, prompt = asyncio.run(read_guidance())
    catalog = json.loads(catalog_content[0].text)
    reason_codes = json.loads(reasons_content[0].text)

    assert catalog["mode"] == "read_only"
    assert "application_stats_get" in catalog["tools"]["applications"]
    assert reason_codes["reason_codes"]["pressure_high"]
    assert "application_stats_get" in prompt.messages[0].content.text


def test_mcp_cli_manifest_is_machine_readable() -> None:
    """The FastMCP CLI should emit parseable JSON for tools, resources, and prompts."""

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "fastmcp.cli",
            "list",
            "app/mcp/core/server.py",
            "--resources",
            "--prompts",
            "--json",
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert {tool["name"] for tool in manifest["tools"]} >= {"application_list", "machine_get"}
    assert {resource["uri"] for resource in manifest["resources"]} == {
        "metrics-collector://mcp/catalog",
        "metrics-collector://optimizations/reason-codes",
    }
    assert {prompt["name"] for prompt in manifest["prompts"]} == {
        "application_capacity_review",
        "machine_optimization_explanation",
        "inventory_scope_discovery",
    }


def test_mcp_tools_return_common_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every exposed tool should return status, message, data, pagination, and error."""

    downstream = _build_downstream_app()
    calls = [
        ("application_list", {}),
        ("application_search", {"query": "billing"}),
        ("application_get", {"application_id": 1}),
        ("application_regions_list", {}),
        ("application_environments_list", {}),
        ("machine_list", {}),
        ("machine_search", {"query": "billing"}),
        ("machine_get", {"machine_id": 42}),
        ("application_stats_get", {"application_id": 1, "window_days": 7}),
        ("application_optimizations_get", {"application_id": 1}),
    ]

    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            results = [
                asyncio.run(_call_http_tool(f"{mcp_server.base_url}/mcp", tool_name, arguments))
                for tool_name, arguments in calls
            ]

    for result in results:
        assert set(result) == {"status", "message", "data", "pagination", "error"}
        assert result["status"] == "success"
        assert result["message"]
        assert isinstance(result["data"], dict)
        assert result["error"] is None


def test_mcp_tool_calls_emit_observability_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool calls should record per-tool status and latency metrics."""

    downstream = _build_downstream_app()
    with LiveServer(downstream) as downstream_server:
        monkeypatch.setenv("MCP_API_BASE_URL", downstream_server.base_url)
        with LiveServer(create_app()) as mcp_server:
            asyncio.run(
                _call_http_tool(
                    f"{mcp_server.base_url}/mcp",
                    "application_list",
                    {"page_size": 1},
                    authorization="Bearer metrics",
                )
            )

    metrics = generate_latest().decode("utf-8")
    assert "mcp_tool_calls_total" in metrics
    assert 'tool_name="application_list"' in metrics
    assert 'status="success"' in metrics
    assert "mcp_tool_duration_seconds_count" in metrics


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
    async def applications(request: Request) -> dict[str, object]:
        """Return stable application collection payload."""

        payload = APPLICATION_LIST_PAYLOAD.copy()
        payload["offset"] = int(request.query_params.get("offset", 0))
        payload["limit"] = int(request.query_params.get("limit", 25))
        return payload

    @app.get("/v1/applications/regions")
    async def application_regions() -> dict[str, object]:
        """Return stable application regions."""

        return APPLICATION_REGIONS_PAYLOAD

    @app.get("/v1/applications/environments")
    async def application_environments() -> dict[str, object]:
        """Return stable application environments."""

        return APPLICATION_DIMENSIONS_PAYLOAD

    @app.get("/v1/applications/{application_id}/stats")
    async def application_stats(application_id: int) -> dict[str, object]:
        """Return stable application stats."""

        if application_id == 404:
            return JSONResponse(status_code=404, content={"detail": "application not found"})
        return APPLICATION_STATS_PAYLOAD

    @app.get("/v1/applications/{application_id}/optimizations/summary")
    async def application_optimizations(application_id: int) -> dict[str, object]:
        """Return stable application optimization summary."""

        if application_id == 404:
            return JSONResponse(status_code=404, content={"detail": "application not found"})
        return APPLICATION_OPTIMIZATIONS_PAYLOAD

    @app.get("/v1/applications/{application_id}")
    async def application(application_id: int):
        """Return one application or a controlled 404."""

        if application_id == 404:
            return JSONResponse(status_code=404, content={"detail": "application not found"})
        if application_id == 500:
            return {"id": 500, "name": "BROKEN"}
        return APPLICATION_PAYLOAD

    @app.get("/v1/machines")
    async def machines(request: Request) -> dict[str, object]:
        """Return stable machine collection payload."""

        payload = MACHINE_LIST_PAYLOAD.copy()
        payload["offset"] = int(request.query_params.get("offset", 0))
        payload["limit"] = int(request.query_params.get("limit", 25))
        return payload

    @app.get("/v1/machines/{machine_id}/metrics/latest")
    async def machine_latest_metrics(machine_id: int) -> dict[str, object]:
        """Return stable latest machine metrics."""

        if machine_id == 404:
            return JSONResponse(status_code=404, content={"detail": "machine not found"})
        return LATEST_METRICS_PAYLOAD

    @app.get("/v1/machines/{machine_id}/optimizations")
    async def machine_optimization(machine_id: int):
        """Return stable current machine optimization."""

        if machine_id == 404:
            return JSONResponse(status_code=404, content={"detail": "optimization not computed yet"})
        return OPTIMIZATION_PAYLOAD

    @app.get("/v1/machines/{machine_id}")
    async def machine(machine_id: int):
        """Return one machine or a controlled 404."""

        if machine_id == 404:
            return JSONResponse(status_code=404, content={"detail": "machine not found"})
        return MACHINE_PAYLOAD

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
