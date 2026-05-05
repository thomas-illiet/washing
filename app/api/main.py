"""FastAPI application factory and Swagger customization."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import applications, health, machines, metric_types, metrics, platforms, providers, provisioners
from internal.infra.config.settings import get_settings
from internal.infra.observability.prometheus import prometheus_http_middleware, prometheus_response

STATIC_DIR = Path(__file__).resolve().parent / "static"
SWAGGER_THEME_PATH = "/static/swagger-washing.css"


def _inject_swagger_theme(response: HTMLResponse) -> HTMLResponse:
    """Inject the local CSS theme into the generated Swagger page."""
    themed_html = response.body.decode("utf-8").replace(
        "</head>",
        f'  <link rel="stylesheet" type="text/css" href="{SWAGGER_THEME_PATH}">\n</head>',
    )
    return HTMLResponse(content=themed_html, status_code=response.status_code)


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
    app.include_router(metric_types.router)
    app.include_router(provisioners.router)
    app.include_router(providers.router)
    app.include_router(metrics.router)

    @app.get("/", include_in_schema=False)
    def root() -> HTMLResponse:
        """Serve the customized Swagger UI at the application root."""
        swagger_ui = get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{settings.app_name} API",
            swagger_ui_parameters={
                "docExpansion": "list",
                "defaultModelsExpandDepth": -1,
                "displayRequestDuration": True,
                "filter": True,
            },
        )
        return _inject_swagger_theme(swagger_ui)

    return app


app = create_app()
