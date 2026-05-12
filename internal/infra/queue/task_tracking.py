"""Celery task execution tracking persisted in the application database."""

from collections.abc import Mapping, Sequence
from datetime import datetime

from celery.signals import before_task_publish, task_failure, task_postrun, task_prerun, task_retry
from sqlalchemy.exc import IntegrityError

from internal.infra.db.base import utcnow
from internal.infra.db.models import CeleryTaskExecution
from internal.infra.db.session import SessionLocal
from internal.infra.queue.task_names import (
    RECALCULATE_MACHINE_RECOMMENDATIONS_TASK,
    RUN_PROVIDER_MACHINE_TASK,
    RUN_PROVIDER_TASK,
    RUN_PROVISIONER_TASK,
    SYNC_APPLICATION_METRICS_TASK,
)
from internal.infra.security import sanitize_operational_error, sanitize_task_result


RESOURCE_TYPE_HEADER = "x-resource-type"
RESOURCE_ID_HEADER = "x-resource-id"
TASK_RESOURCE_TYPES = {
    RUN_PROVIDER_MACHINE_TASK: "provider",
    RUN_PROVIDER_TASK: "provider",
    RUN_PROVISIONER_TASK: "provisioner",
    SYNC_APPLICATION_METRICS_TASK: "application",
    RECALCULATE_MACHINE_RECOMMENDATIONS_TASK: "machine",
}
TERMINAL_TASK_STATES = {"SUCCESS", "FAILURE", "REVOKED"}
_CELERY_TASK_TRACKING_REGISTERED = False


# Public helper used by the use cases before tasks are published.
def build_task_tracking_headers(task_name: str, args: Sequence[object] | None = None) -> dict[str, object]:
    """Return Celery headers carrying the task tracking business context."""
    resource_type = TASK_RESOURCE_TYPES.get(task_name)
    resource_id = _coerce_resource_id(args[0]) if args else None
    headers: dict[str, object] = {}
    if resource_type is not None:
        headers[RESOURCE_TYPE_HEADER] = resource_type
    if resource_id is not None:
        headers[RESOURCE_ID_HEADER] = resource_id
    return headers


def configure_celery_task_tracking() -> None:
    """Register Celery signal handlers used to persist task execution history."""
    global _CELERY_TASK_TRACKING_REGISTERED
    if _CELERY_TASK_TRACKING_REGISTERED:
        return

    # Publish-time signals create the initial row as soon as the task leaves the API layer.
    @before_task_publish.connect(weak=False)
    def _record_task_publish(
        sender: str | None = None,
        headers: Mapping[str, object] | None = None,
        body: object | None = None,
        **_: object,
    ) -> None:
        """Persist a pending execution row when Celery publishes a tracked task."""
        task_id = _published_task_id(headers, body)
        task_name = sender or _published_task_name(headers, body)
        if task_id is None or task_name is None:
            return

        args = _published_args(body)
        resource_type, resource_id = _resolve_resource_context(task_name, headers=headers, args=args)
        _create_execution_if_missing(
            task_id=task_id,
            task_name=task_name,
            status="PENDING",
            queued_at=utcnow(),
            resource_type=resource_type,
            resource_id=resource_id,
        )

    @task_prerun.connect(weak=False)
    def _record_task_start(
        task_id: str | None = None,
        task: object | None = None,
        args: Sequence[object] | None = None,
        **_: object,
    ) -> None:
        """Mark a tracked task execution as started just before task runtime."""
        task_name = getattr(task, "name", None)
        if task_id is None or task_name is None:
            return

        now = utcnow()
        request_headers = _task_request_headers(task)
        resource_type, resource_id = _resolve_resource_context(task_name, headers=request_headers, args=args)

        def mutate(execution: CeleryTaskExecution) -> None:
            """Apply the runtime-start state transition to one execution row."""
            execution.status = "STARTED"
            execution.resource_type = execution.resource_type or resource_type
            execution.resource_id = execution.resource_id if execution.resource_id is not None else resource_id
            execution.queued_at = execution.queued_at or now
            execution.started_at = now
            execution.finished_at = None
            execution.duration_seconds = None
            execution.result = None
            execution.error = None

        _mutate_execution(
            task_id=task_id,
            task_name=task_name,
            resource_type=resource_type,
            resource_id=resource_id,
            queued_at=now,
            mutate=mutate,
        )

    @task_postrun.connect(weak=False)
    def _record_task_finish(
        task_id: str | None = None,
        task: object | None = None,
        state: str | None = None,
        retval: object | None = None,
        **_: object,
    ) -> None:
        """Persist the terminal or post-run state emitted by Celery."""
        task_name = getattr(task, "name", None)
        if task_id is None or task_name is None or state is None:
            return

        now = utcnow()
        request_headers = _task_request_headers(task)
        args = _task_request_args(task)
        resource_type, resource_id = _resolve_resource_context(task_name, headers=request_headers, args=args)

        def mutate(execution: CeleryTaskExecution) -> None:
            """Apply the post-run task state, duration, and result payload."""
            execution.status = state
            execution.resource_type = execution.resource_type or resource_type
            execution.resource_id = execution.resource_id if execution.resource_id is not None else resource_id

            if state in TERMINAL_TASK_STATES:
                execution.finished_at = now
                if execution.started_at is not None:
                    execution.duration_seconds = _duration_seconds(execution.started_at, now)

            if state == "SUCCESS":
                execution.result = sanitize_task_result(retval)
                execution.error = None

        _mutate_execution(
            task_id=task_id,
            task_name=task_name,
            resource_type=resource_type,
            resource_id=resource_id,
            queued_at=now,
            mutate=mutate,
        )

    @task_failure.connect(weak=False)
    def _record_task_failure(
        task_id: str | None = None,
        exception: BaseException | None = None,
        sender: object | None = None,
        args: Sequence[object] | None = None,
        **_: object,
    ) -> None:
        """Capture task failures and persist the rendered error message."""
        task_name = getattr(sender, "name", None)
        if task_id is None or task_name is None:
            return

        request_headers = _task_request_headers(sender)
        resource_type, resource_id = _resolve_resource_context(task_name, headers=request_headers, args=args)

        def mutate(execution: CeleryTaskExecution) -> None:
            """Apply the failure state transition to one execution row."""
            execution.status = "FAILURE"
            execution.resource_type = execution.resource_type or resource_type
            execution.resource_id = execution.resource_id if execution.resource_id is not None else resource_id
            execution.error = _stringify_error(exception)

        _mutate_execution(
            task_id=task_id,
            task_name=task_name,
            resource_type=resource_type,
            resource_id=resource_id,
            queued_at=utcnow(),
            mutate=mutate,
        )

    @task_retry.connect(weak=False)
    def _record_task_retry(
        request: object | None = None,
        reason: BaseException | str | None = None,
        sender: object | None = None,
        **_: object,
    ) -> None:
        """Persist retry state changes emitted by Celery tasks."""
        task_id = getattr(request, "id", None)
        task_name = getattr(sender, "name", None)
        if task_id is None or task_name is None:
            return

        request_headers = _task_request_headers(sender)
        args = getattr(request, "args", None)
        resource_type, resource_id = _resolve_resource_context(task_name, headers=request_headers, args=args)

        def mutate(execution: CeleryTaskExecution) -> None:
            """Apply the retry state transition to one execution row."""
            execution.status = "RETRY"
            execution.resource_type = execution.resource_type or resource_type
            execution.resource_id = execution.resource_id if execution.resource_id is not None else resource_id
            execution.error = _stringify_error(reason)

        _mutate_execution(
            task_id=task_id,
            task_name=task_name,
            resource_type=resource_type,
            resource_id=resource_id,
            queued_at=utcnow(),
            mutate=mutate,
        )

    _CELERY_TASK_TRACKING_REGISTERED = True


# Database mutation helpers.
def _create_execution_if_missing(
    task_id: str,
    task_name: str,
    status: str,
    queued_at: datetime,
    resource_type: str | None,
    resource_id: int | None,
) -> None:
    """Insert the tracked task row when it does not exist yet."""
    db = SessionLocal()
    try:
        existing = db.query(CeleryTaskExecution).filter(CeleryTaskExecution.task_id == task_id).one_or_none()
        if existing is not None:
            return

        db.add(
            CeleryTaskExecution(
                task_id=task_id,
                task_name=task_name,
                status=status,
                resource_type=resource_type,
                resource_id=resource_id,
                queued_at=queued_at,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def _mutate_execution(
    task_id: str,
    task_name: str,
    resource_type: str | None,
    resource_id: int | None,
    queued_at: datetime,
    mutate,
) -> None:
    """Load or create a tracked task execution, mutate it, and commit it."""
    db = SessionLocal()
    try:
        execution = db.query(CeleryTaskExecution).filter(CeleryTaskExecution.task_id == task_id).one_or_none()
        if execution is None:
            execution = CeleryTaskExecution(
                task_id=task_id,
                task_name=task_name,
                status="PENDING",
                resource_type=resource_type,
                resource_id=resource_id,
                queued_at=queued_at,
            )
            db.add(execution)

        try:
            mutate(execution)
            db.commit()
        except IntegrityError:
            db.rollback()
            # Another worker may have inserted the row first between load and commit.
            execution = db.query(CeleryTaskExecution).filter(CeleryTaskExecution.task_id == task_id).one()
            mutate(execution)
            db.commit()
    finally:
        db.close()


# Celery signal payload parsing helpers.
def _published_task_id(headers: Mapping[str, object] | None, body: object | None) -> str | None:
    """Extract the task id from a before_task_publish signal payload."""
    if headers is not None:
        candidate = headers.get("id")
        if isinstance(candidate, str):
            return candidate

    if isinstance(body, Mapping):
        candidate = body.get("id")
        if isinstance(candidate, str):
            return candidate
    return None


def _published_task_name(headers: Mapping[str, object] | None, body: object | None) -> str | None:
    """Extract the task name from a before_task_publish signal payload."""
    if headers is not None:
        candidate = headers.get("task")
        if isinstance(candidate, str):
            return candidate

    if isinstance(body, Mapping):
        candidate = body.get("task")
        if isinstance(candidate, str):
            return candidate
    return None


def _published_args(body: object | None) -> tuple[object, ...]:
    """Extract task args from a before_task_publish signal payload."""
    if isinstance(body, Sequence) and not isinstance(body, (str, bytes)) and body:
        maybe_args = body[0]
        if isinstance(maybe_args, Sequence) and not isinstance(maybe_args, (str, bytes)):
            return tuple(maybe_args)

    if isinstance(body, Mapping):
        maybe_args = body.get("args")
        if isinstance(maybe_args, Sequence) and not isinstance(maybe_args, (str, bytes)):
            return tuple(maybe_args)

    return ()


def _task_request_headers(task: object | None) -> Mapping[str, object] | None:
    """Return custom request headers from a Celery task instance when present."""
    request = getattr(task, "request", None)
    headers = getattr(request, "headers", None)
    if isinstance(headers, Mapping):
        return headers
    return None


def _task_request_args(task: object | None) -> tuple[object, ...]:
    """Return task request args from a Celery task instance when present."""
    request = getattr(task, "request", None)
    args = getattr(request, "args", None)
    if isinstance(args, Sequence) and not isinstance(args, (str, bytes)):
        return tuple(args)
    return ()


def _resolve_resource_context(
    task_name: str,
    headers: Mapping[str, object] | None,
    args: Sequence[object] | None,
) -> tuple[str | None, int | None]:
    """Resolve tracked resource metadata from headers first, then task args."""
    # Prefer explicit publish headers so retries keep the same business linkage.
    resource_type = _string_or_none(headers.get(RESOURCE_TYPE_HEADER)) if headers is not None else None
    if resource_type is None:
        resource_type = TASK_RESOURCE_TYPES.get(task_name)

    resource_id = _coerce_resource_id(headers.get(RESOURCE_ID_HEADER)) if headers is not None else None
    if resource_id is None and resource_type is not None and args:
        resource_id = _coerce_resource_id(args[0])

    return resource_type, resource_id


# Small coercion helpers shared by the signal handlers.
def _duration_seconds(started_at: datetime, finished_at: datetime) -> float:
    """Compute a non-negative duration while tolerating naive SQLite timestamps."""
    if started_at.tzinfo is None and finished_at.tzinfo is not None:
        finished_at = finished_at.replace(tzinfo=None)
    elif started_at.tzinfo is not None and finished_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=None)
    return max(0.0, (finished_at - started_at).total_seconds())


def _coerce_resource_id(value: object) -> int | None:
    """Convert a task resource id candidate to an integer when possible."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _string_or_none(value: object) -> str | None:
    """Return a string value when the candidate is a non-empty string."""
    if isinstance(value, str) and value:
        return value
    return None


def _stringify_error(value: BaseException | str | None) -> str | None:
    """Render Celery failure and retry reasons as a short message."""
    return sanitize_operational_error(value)
