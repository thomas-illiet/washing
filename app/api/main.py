"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import applications, health, machines, platforms, providers, provisioners, tasks
from internal.infra.config.settings import get_settings
from internal.infra.observability.prometheus import prometheus_http_middleware, prometheus_response


STATIC_DIR = Path(__file__).with_name("static")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None)
    app.middleware("http")(prometheus_http_middleware)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    if settings.prometheus_api_enabled:
        app.add_api_route(settings.prometheus_api_path, prometheus_response, methods=["GET"], include_in_schema=False)

    app.include_router(health.router)
    app.include_router(platforms.router)
    app.include_router(applications.router)
    app.include_router(machines.router)
    app.include_router(provisioners.router)
    app.include_router(providers.router)
    app.include_router(tasks.router)

    @app.get("/", include_in_schema=False)
    def root() -> HTMLResponse:
        """Serve the Swagger UI at the application root."""
        response = get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{settings.app_name} API",
        )
        html = response.body.decode("utf-8").replace(
            "</head>",
            '    <link rel="stylesheet" href="/static/swagger-washing.css">\n    </head>',
        )
        return HTMLResponse(content=html)

    return app


app = create_app()
