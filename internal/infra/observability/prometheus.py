from time import perf_counter

from celery.signals import task_postrun, task_prerun, worker_ready, worker_shutdown
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest, start_http_server
from starlette.requests import Request
from starlette.responses import Response

from internal.infra.config.settings import get_settings


HTTP_REQUESTS_TOTAL = Counter(
    "api_http_requests_total",
    "Total API HTTP requests.",
    ["method", "route", "status_code"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "api_http_request_duration_seconds",
    "API HTTP request duration in seconds.",
    ["method", "route"],
)

CELERY_TASKS_TOTAL = Counter(
    "celery_tasks_total",
    "Total Celery task executions by final state.",
    ["task_name", "state"],
)
CELERY_TASK_DURATION_SECONDS = Histogram(
    "celery_task_duration_seconds",
    "Celery task duration in seconds.",
    ["task_name"],
)
CELERY_TASKS_IN_PROGRESS = Gauge(
    "celery_tasks_in_progress",
    "Celery tasks currently running.",
    ["task_name"],
)
CELERY_WORKER_UP = Gauge(
    "celery_worker_up",
    "Whether the Celery worker metrics process is running.",
)

_TASK_START_TIMES: dict[str, float] = {}
_CELERY_SIGNALS_REGISTERED = False
_CELERY_METRICS_SERVER_STARTED = False


def prometheus_response() -> Response:
    return Response(content=generate_latest(), headers={"Content-Type": CONTENT_TYPE_LATEST})


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path is not None:
        return path
    return "__unmatched__"


def observe_api_request(method: str, route: str, status_code: int, duration_seconds: float) -> None:
    labels = {"method": method, "route": route, "status_code": str(status_code)}
    HTTP_REQUESTS_TOTAL.labels(**labels).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route).observe(duration_seconds)


async def prometheus_http_middleware(request: Request, call_next):
    settings = get_settings()
    if not settings.prometheus_api_enabled or request.url.path == settings.prometheus_api_path:
        return await call_next(request)

    started_at = perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        observe_api_request(
            method=request.method,
            route=route_template(request),
            status_code=status_code,
            duration_seconds=perf_counter() - started_at,
        )


def configure_celery_prometheus() -> None:
    global _CELERY_SIGNALS_REGISTERED
    if _CELERY_SIGNALS_REGISTERED:
        return

    @worker_ready.connect(weak=False)
    def _start_metrics_server(**_: object) -> None:
        start_celery_metrics_server()

    @worker_shutdown.connect(weak=False)
    def _mark_worker_down(**_: object) -> None:
        CELERY_WORKER_UP.set(0)

    @task_prerun.connect(weak=False)
    def _record_task_start(task_id: str | None = None, task: object | None = None, **_: object) -> None:
        task_name = getattr(task, "name", "unknown")
        if task_id is not None:
            _TASK_START_TIMES[task_id] = perf_counter()
        CELERY_TASKS_IN_PROGRESS.labels(task_name=task_name).inc()

    @task_postrun.connect(weak=False)
    def _record_task_finish(
        task_id: str | None = None,
        task: object | None = None,
        state: str | None = None,
        **_: object,
    ) -> None:
        task_name = getattr(task, "name", "unknown")
        started_at = _TASK_START_TIMES.pop(task_id, None) if task_id is not None else None
        if started_at is not None:
            CELERY_TASK_DURATION_SECONDS.labels(task_name=task_name).observe(perf_counter() - started_at)
        CELERY_TASKS_TOTAL.labels(task_name=task_name, state=state or "UNKNOWN").inc()
        CELERY_TASKS_IN_PROGRESS.labels(task_name=task_name).dec()

    _CELERY_SIGNALS_REGISTERED = True


def start_celery_metrics_server() -> None:
    global _CELERY_METRICS_SERVER_STARTED
    settings = get_settings()
    if not settings.celery_prometheus_enabled or _CELERY_METRICS_SERVER_STARTED:
        return

    start_http_server(settings.celery_prometheus_port)
    CELERY_WORKER_UP.set(1)
    _CELERY_METRICS_SERVER_STARTED = True
