"""ASGI entrypoint for the FastMCP gateway."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.mcp.core import mcp
from internal.infra.auth import OIDCAuthenticationError, authorize_request
from internal.infra.observability import configure_uvicorn_access_log_filter


def create_app() -> FastAPI:
    """Create a fresh FastAPI wrapper around the FastMCP HTTP app."""
    configure_uvicorn_access_log_filter({"/health"})
    mcp_app = mcp.http_app(path="/", stateless_http=True)
    app = FastAPI(title="Metrics Collector MCP", lifespan=mcp_app.lifespan)

    @app.middleware("http")
    async def oidc_http_middleware(request: Request, call_next):
        """Protect the MCP HTTP transport with the shared OIDC user role."""
        if request.url.path != "/health" and request.url.path.startswith("/mcp"):
            try:
                await authorize_request(request, required_role="user")
            except OIDCAuthenticationError as exc:
                headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Simple health endpoint for probes."""

        return {"status": "ok"}

    app.mount("/mcp", mcp_app)
    return app


app = create_app()
