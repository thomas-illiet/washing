"""ASGI entrypoint for the FastMCP gateway."""

from fastapi import FastAPI

from app.mcp.server import mcp


def create_app() -> FastAPI:
    """Create a fresh FastAPI wrapper around the FastMCP HTTP app."""

    mcp_app = mcp.http_app(path="/", stateless_http=True)
    app = FastAPI(title="Metrics Collector MCP", lifespan=mcp_app.lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Simple health endpoint for probes."""

        return {"status": "ok"}

    app.mount("/mcp", mcp_app)
    return app


app = create_app()
