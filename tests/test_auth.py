"""Tests covering OIDC authentication and RBAC behavior."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.main import create_app as create_api_app
from app.mcp.main import create_app as create_mcp_app
from app.mcp.config import get_settings as get_mcp_settings
from internal.infra.auth import clear_oidc_caches
from internal.infra.config.settings import get_settings


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


class FakeOIDCProvider:
    """In-process OIDC provider exposing discovery and JWKS endpoints."""

    def __init__(self) -> None:
        """Generate a reusable RSA keypair and the ASGI routes around it."""
        from cryptography.hazmat.primitives.asymmetric import rsa

        self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self._public_jwk = RSAAlgorithm.to_jwk(self._private_key.public_key())
        self.issuer = ""
        self.app = FastAPI()

        @self.app.get("/.well-known/openid-configuration")
        async def openid_configuration() -> JSONResponse:
            return JSONResponse(
                {
                    "issuer": self.issuer,
                    "authorization_endpoint": f"{self.issuer}/protocol/openid-connect/auth",
                    "token_endpoint": f"{self.issuer}/protocol/openid-connect/token",
                    "jwks_uri": f"{self.issuer}/jwks.json",
                }
            )

        @self.app.get("/jwks.json")
        async def jwks() -> JSONResponse:
            return JSONResponse({"keys": [{**json.loads(self._public_jwk), "kid": "test-kid"}]})

    def issue_token(
        self,
        *,
        roles: list[str],
        audience: str | None = None,
        roles_claim: str = "realm_access",
    ) -> str:
        """Issue one signed JWT access token for test callers."""
        now = datetime.now(timezone.utc)
        claims: dict[str, object] = {
            "iss": self.issuer,
            "sub": "user-123",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
            "preferred_username": "reader",
        }
        if audience is not None:
            claims["aud"] = audience
        if roles_claim == "realm_access":
            claims["realm_access"] = {"roles": roles}
        else:
            claims[roles_claim] = roles

        return jwt.encode(
            claims,
            self._private_key,
            algorithm="RS256",
            headers={"kid": "test-kid"},
        )


@pytest.fixture()
def oidc_provider() -> Iterator[FakeOIDCProvider]:
    """Run a fake OIDC provider on a live local port."""
    provider = FakeOIDCProvider()
    server = LiveServer(provider.app)
    provider.issuer = server.base_url
    with server:
        yield provider


def _build_api_client(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    oidc_provider: FakeOIDCProvider,
) -> TestClient:
    """Build an API client wired to the in-memory DB and fake OIDC provider."""
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER_URL", oidc_provider.issuer)
    monkeypatch.setenv("OIDC_DISCOVERY_URL", f"{oidc_provider.issuer}/.well-known/openid-configuration")
    monkeypatch.setenv("OIDC_SWAGGER_CLIENT_ID", "washing-machine-swagger")
    clear_oidc_caches()
    get_settings.cache_clear()
    app = create_api_app()

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def test_oidc_user_can_read_but_not_mutate(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    oidc_provider: FakeOIDCProvider,
) -> None:
    """A `user` role should read protected resources but not execute writes."""
    client = _build_api_client(db_session, monkeypatch, oidc_provider)
    user_headers = {"Authorization": f"Bearer {oidc_provider.issue_token(roles=['user'])}"}
    admin_headers = {"Authorization": f"Bearer {oidc_provider.issue_token(roles=['user', 'admin'])}"}

    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 401
    assert client.get("/v1/openapi.json").status_code == 401
    assert client.get("/", headers={"accept": "text/html"}).status_code == 200

    list_response = client.get("/v1/platforms", headers=user_headers)
    assert list_response.status_code == 200
    assert list_response.json() == {"items": [], "offset": 0, "limit": 100, "total": 0}

    openapi_response = client.get("/v1/openapi.json", headers=user_headers)
    assert openapi_response.status_code == 200
    assert "oidc" in openapi_response.json()["components"]["securitySchemes"]

    forbidden_create = client.post("/v1/platforms", json={"name": "AWS"}, headers=user_headers)
    assert forbidden_create.status_code == 403

    forbidden_sync = client.post("/v1/applications/sync", params={"type": "metrics"}, headers=user_headers)
    assert forbidden_sync.status_code == 403

    created = client.post("/v1/platforms", json={"name": "AWS"}, headers=admin_headers)
    assert created.status_code == 201
    assert created.json()["name"] == "AWS"

    limited = client.get("/v1/platforms", params={"limit": 201}, headers=user_headers)
    assert limited.status_code == 422


def test_oidc_supports_generic_roles_claim_path(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    oidc_provider: FakeOIDCProvider,
) -> None:
    """The auth layer should work with non-Keycloak providers exposing a flat `roles` claim."""
    monkeypatch.setenv("OIDC_ROLE_CLAIM_PATHS", "roles")
    client = _build_api_client(db_session, monkeypatch, oidc_provider)
    admin_headers = {"Authorization": f"Bearer {oidc_provider.issue_token(roles=['admin'], roles_claim='roles')}"}

    response = client.post("/v1/platforms", json={"name": "Azure"}, headers=admin_headers)
    assert response.status_code == 201
    assert response.json()["name"] == "Azure"


def test_oidc_supports_custom_role_names(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    oidc_provider: FakeOIDCProvider,
) -> None:
    """The read/write roles should follow configuration instead of hardcoded names."""
    monkeypatch.setenv("OIDC_USER_ROLE_NAME", "viewer")
    monkeypatch.setenv("OIDC_ADMIN_ROLE_NAME", "operator")
    client = _build_api_client(db_session, monkeypatch, oidc_provider)
    viewer_headers = {"Authorization": f"Bearer {oidc_provider.issue_token(roles=['viewer'])}"}
    operator_headers = {"Authorization": f"Bearer {oidc_provider.issue_token(roles=['viewer', 'operator'])}"}

    assert client.get("/v1/platforms", headers=viewer_headers).status_code == 200
    assert client.post("/v1/platforms", json={"name": "GCP"}, headers=viewer_headers).status_code == 403

    created = client.post("/v1/platforms", json={"name": "GCP"}, headers=operator_headers)
    assert created.status_code == 201
    assert created.json()["name"] == "GCP"


def test_mcp_requires_a_user_token_when_oidc_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
    oidc_provider: FakeOIDCProvider,
) -> None:
    """The MCP transport should require an authenticated user once OIDC is enabled."""
    monkeypatch.setenv("OIDC_ENABLED", "true")
    monkeypatch.setenv("OIDC_ISSUER_URL", oidc_provider.issuer)
    monkeypatch.setenv("OIDC_DISCOVERY_URL", f"{oidc_provider.issuer}/.well-known/openid-configuration")
    clear_oidc_caches()
    get_mcp_settings.cache_clear()
    client = TestClient(create_mcp_app(), raise_server_exceptions=False)

    assert client.get("/health").status_code == 200
    assert client.post("/mcp").status_code == 401
    authorized = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {oidc_provider.issue_token(roles=['user'])}"},
    )
    assert authorized.status_code != 401


def _free_tcp_port() -> int:
    """Return an available local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])
