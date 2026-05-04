from fastapi import FastAPI

from app.api.routes import applications, health, machines, metric_types, metrics, platforms, providers, provisioners
from app.core.config import get_settings
from app.core.prometheus import prometheus_http_middleware, prometheus_response


settings = get_settings()

app = FastAPI(title=settings.app_name)
app.middleware("http")(prometheus_http_middleware)

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


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name}
