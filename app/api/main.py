"""FastAPI application factory."""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.docs import (
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
    swagger_ui_default_parameters,
)
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import applications, discovery, health, machines, platforms, tasks
from app.api.routes.machines import mock_providers, mock_provisioners
from internal.infra.auth import (
    OIDCAuthenticationError,
    authorize_request,
    get_oidc_settings,
    oidc_docs_shell_is_public,
    swagger_oauth_config,
    swagger_security_scheme,
)
from internal.infra.config.settings import get_settings
from internal.infra.db.readiness import ensure_database_schema_is_current
from internal.infra.observability import configure_uvicorn_access_log_filter
from internal.infra.observability.prometheus import prometheus_http_middleware, prometheus_response

API_V1_PREFIX = "/v1"
OAUTH2_REDIRECT_PATH = "/oauth2-redirect"
STATIC_DIR = Path(__file__).resolve().parent / "static"
SWAGGER_FAVICON_URL = "/static/swagger-tag-images/machines.png"
OPENAPI_DESCRIPTION = """
Inventory and machine metrics API for platforms, applications, providers, and provisioners.

Use this documentation to browse collection endpoints, operational actions, and async worker tasks.
""".strip()

OPENAPI_TAGS = [
    {"name": "Platforms", "description": "Cycle programs and settings."},
    {"name": "Applications", "description": "Loads to track in the drum."},
    {"name": "Discovery", "description": "Assistant-ready inventory and optimization discovery."},
    {"name": "Machines", "description": "Main drum and inventory."},
    {"name": "Machine Optimizations", "description": "Capacity advice and acknowledged wash labels."},
    {"name": "Machine Metrics", "description": "CPU, RAM, and disk spin cycle."},
    {"name": "Machine Providers", "description": "Water inlets and metric sources."},
    {"name": "Machine Provisioners", "description": "Detergent drawers and inventory connectors."},
    {"name": "Tasks", "description": "Asynchronous porthole queue."},
]


def _swagger_ui_parameters() -> dict[str, object]:
    """Return the shared Swagger UI presentation settings."""
    parameters = swagger_ui_default_parameters.copy()
    parameters.update(
        {
            "deepLinking": False,
            "docExpansion": "none",
            "defaultModelsExpandDepth": -1,
        }
    )
    return parameters


def _public_docs_html(app: FastAPI, title: str) -> HTMLResponse:
    """Render Swagger UI with an embedded OpenAPI schema."""
    swagger_ui_parameters = _swagger_ui_parameters()
    init_oauth = swagger_oauth_config()
    # Embed the schema so the docs shell still works when the JSON route is protected.
    schema = json.dumps(jsonable_encoder(app.openapi()))
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="icon" type="image/png" href="{SWAGGER_FAVICON_URL}">
    <link type="text/css" rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
    <link type="text/css" rel="stylesheet" href="/static/swagger-washing-machine.css">
    <title>{title}</title>
    </head>
    <body>
    <div id="swagger-ui"></div>
    <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
    const ui = SwaggerUIBundle({{
        spec: {schema},
        {json.dumps("presets")}: [
            SwaggerUIBundle.presets.apis,
            SwaggerUIBundle.SwaggerUIStandalonePreset
        ],
        {json.dumps("oauth2RedirectUrl")}: window.location.origin + "{OAUTH2_REDIRECT_PATH}",
    """
    for key, value in swagger_ui_parameters.items():
        html += f"{json.dumps(key)}: {json.dumps(jsonable_encoder(value))},\n"
    html += "})\n"
    if init_oauth is not None:
        html += f"ui.initOAuth({json.dumps(jsonable_encoder(init_oauth))})\n"
    html += """
    </script>
    </body>
    </html>
    """
    return HTMLResponse(html)


def _required_role_for_api_request(request: Request) -> str | None:
    """Return the role required for one API request, if any."""
    settings = get_settings()
    path = request.url.path
    method = request.method.upper()

    if method == "OPTIONS":
        return None
    if path == "/health" or path == OAUTH2_REDIRECT_PATH or path.startswith("/static/"):
        return None
    if settings.prometheus_api_enabled and path == settings.prometheus_api_path:
        return None
    if path == "/" and oidc_docs_shell_is_public(request, get_oidc_settings()):
        # Keep the HTML shell reachable so Swagger can initiate the login flow.
        return None
    if path == "/" or path == (request.app.openapi_url or "/openapi.json") or path.startswith(f"{API_V1_PREFIX}/"):
        # Reads stay broadly visible; mutations and executions require the write role.
        return "user" if method in {"GET", "HEAD"} else "admin"
    return None


def _configure_openapi_security(app: FastAPI) -> None:
    """Attach a custom OpenAPI generator that advertises OIDC security."""

    def custom_openapi() -> dict:
        """Build and cache the customized OpenAPI document."""
        if app.openapi_schema is not None:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=OPENAPI_TAGS,
        )
        security_scheme = swagger_security_scheme()
        if security_scheme is not None:
            schema.setdefault("components", {}).setdefault("securitySchemes", {})["oidc"] = security_scheme
            # Mark every versioned business route as protected in the generated contract.
            for path, operations in schema.get("paths", {}).items():
                if not path.startswith(API_V1_PREFIX):
                    continue
                for method_name, operation in operations.items():
                    if method_name.lower() not in {"get", "head", "post", "patch", "delete"}:
                        continue
                    operation["security"] = [{"oidc": []}]

        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi


def create_app(*, validate_database_on_startup: bool = True) -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    hidden_access_paths = {"/health"}
    if settings.prometheus_api_enabled:
        hidden_access_paths.add(settings.prometheus_api_path)
    configure_uvicorn_access_log_filter(hidden_access_paths)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Validate database readiness before serving requests."""
        if validate_database_on_startup:
            ensure_database_schema_is_current()
        yield

    app = FastAPI(
        title=settings.app_name,
        description=OPENAPI_DESCRIPTION,
        docs_url=None,
        redoc_url=None,
        openapi_url=f"{API_V1_PREFIX}/openapi.json",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.middleware("http")
    async def oidc_http_middleware(request: Request, call_next):
        """Protect business routes with role-aware OIDC authorization."""
        required_role = _required_role_for_api_request(request)
        if required_role is not None:
            try:
                await authorize_request(request, required_role=required_role)
            except OIDCAuthenticationError as exc:
                headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
                return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)
        return await call_next(request)

    app.middleware("http")(prometheus_http_middleware)

    if settings.prometheus_api_enabled:
        app.add_api_route(settings.prometheus_api_path, prometheus_response, methods=["GET"], include_in_schema=False)

    app.include_router(health.router)
    app.include_router(platforms.router, prefix=API_V1_PREFIX)
    app.include_router(applications.router, prefix=API_V1_PREFIX)
    app.include_router(discovery.router, prefix=API_V1_PREFIX)
    app.include_router(machines.router, prefix=API_V1_PREFIX)
    if settings.is_dev:
        app.include_router(mock_providers.router, prefix=API_V1_PREFIX)
        app.include_router(mock_provisioners.router, prefix=API_V1_PREFIX)
    app.include_router(tasks.router, prefix=API_V1_PREFIX)
    _configure_openapi_security(app)

    @app.get("/", include_in_schema=False)
    def root(request: Request):
        """Serve the Swagger UI at the application root."""
        oidc_settings = get_oidc_settings()
        if oidc_settings.oidc_enabled:
            return _public_docs_html(app, f"{settings.app_name} API")
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{settings.app_name} API",
            swagger_css_url="/static/swagger-washing-machine.css",
            swagger_favicon_url=SWAGGER_FAVICON_URL,
            swagger_ui_parameters=_swagger_ui_parameters(),
        )

    @app.get(OAUTH2_REDIRECT_PATH, include_in_schema=False)
    def swagger_oauth2_redirect():
        """Serve the OAuth2 redirect helper expected by Swagger UI."""
        return get_swagger_ui_oauth2_redirect_html()

    return app


app = create_app()
