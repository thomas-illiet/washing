"""FastAPI application factory."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

from app.api.routes import applications, health, machines, platforms, tasks
from app.api.routes.machines import mock_providers, mock_provisioners
from internal.infra.config.settings import get_settings
from internal.infra.observability.prometheus import prometheus_http_middleware, prometheus_response

API_V1_PREFIX = "/v1"
STATIC_DIR = Path(__file__).resolve().parent / "static"
OPENAPI_DESCRIPTION = """
Inventory and machine metrics API for platforms, applications, providers, and provisioners.

Use this documentation to browse collection endpoints, operational actions, and async worker tasks.
""".strip()

OPENAPI_TAGS = [
    {"name": "Platforms", "description": "Cycle programs and settings."},
    {"name": "Applications", "description": "Loads to track in the drum."},
    {"name": "Machines", "description": "Main drum and inventory."},
    {"name": "Machine Metrics", "description": "CPU, RAM, and disk spin cycle."},
    {"name": "Machine Providers", "description": "Water inlets and metric sources."},
    {"name": "Machine Provisioners", "description": "Detergent drawers and inventory connectors."},
    {"name": "Tasks", "description": "Asynchronous porthole queue."},
]


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description=OPENAPI_DESCRIPTION,
        docs_url=None,
        redoc_url=None,
        openapi_url=f"{API_V1_PREFIX}/openapi.json",
        openapi_tags=OPENAPI_TAGS,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.middleware("http")(prometheus_http_middleware)

    if settings.prometheus_api_enabled:
        app.add_api_route(settings.prometheus_api_path, prometheus_response, methods=["GET"], include_in_schema=False)

    app.include_router(health.router)
    app.include_router(platforms.router, prefix=API_V1_PREFIX)
    app.include_router(applications.router, prefix=API_V1_PREFIX)
    app.include_router(machines.router, prefix=API_V1_PREFIX)
    if settings.is_dev:
        app.include_router(mock_providers.router, prefix=API_V1_PREFIX)
        app.include_router(mock_provisioners.router, prefix=API_V1_PREFIX)
    app.include_router(tasks.router, prefix=API_V1_PREFIX)

    @app.get("/", include_in_schema=False)
    def root():
        """Serve the Swagger UI at the application root."""
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{settings.app_name} API",
            swagger_css_url="/static/swagger-washing-machine.css",
            swagger_ui_parameters={
                "deepLinking": False,
                "docExpansion": "none",
                "defaultModelsExpandDepth": -1,
            },
        )

    return app


app = create_app()
