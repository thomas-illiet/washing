"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html

from app.api.routes import applications, health, machines, platforms, tasks
from internal.infra.config.settings import get_settings
from internal.infra.observability.prometheus import prometheus_http_middleware, prometheus_response

API_V1_PREFIX = "/v1"

OPENAPI_TAGS = [
    {"name": "platforms"},
    {"name": "applications"},
    {"name": "machines"},
    {"name": "machine-metrics"},
    {"name": "machine-providers"},
    {"name": "machine-provisioners"},
    {"name": "tasks"},
]


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        docs_url=None,
        redoc_url=None,
        openapi_url=f"{API_V1_PREFIX}/openapi.json",
        openapi_tags=OPENAPI_TAGS,
    )
    app.middleware("http")(prometheus_http_middleware)

    if settings.prometheus_api_enabled:
        app.add_api_route(settings.prometheus_api_path, prometheus_response, methods=["GET"], include_in_schema=False)

    app.include_router(health.router)
    app.include_router(platforms.router, prefix=API_V1_PREFIX)
    app.include_router(applications.router, prefix=API_V1_PREFIX)
    app.include_router(machines.router, prefix=API_V1_PREFIX)
    app.include_router(tasks.router, prefix=API_V1_PREFIX)

    @app.get("/", include_in_schema=False)
    def root():
        """Serve the Swagger UI at the application root."""
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{settings.app_name} API",
        )

    return app


app = create_app()
