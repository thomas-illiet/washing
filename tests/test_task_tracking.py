"""Tests for persistent Celery task execution tracking."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from celery.signals import before_task_publish, task_failure, task_postrun, task_prerun, task_retry
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from internal.infra.db.models import Application, CeleryTaskExecution, MachineProvider, MachineProvisioner, Platform
from internal.infra.queue import task_tracking
from internal.infra.queue.task_names import (
    DISPATCH_ENABLED_PROVIDER_SYNCS_TASK,
    DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK,
    RUN_PROVIDER_MACHINE_TASK,
    RUN_PROVISIONER_TASK,
    SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK,
    SYNC_APPLICATION_METRICS_TASK,
)


class FakeTask:
    """Minimal hashable task object for Celery signal tests."""

    def __init__(self, name: str, headers: dict[str, object] | None = None, args: list[object] | None = None) -> None:
        """Populate the task name and request payload expected by signal handlers."""
        self.name = name
        self.request = SimpleNamespace(
            headers=headers or {},
            args=args or [],
        )


@pytest.fixture()
def tracking_session_factory(monkeypatch: pytest.MonkeyPatch, db_session: Session):
    """Bind task tracking signal handlers to the in-memory test database."""
    TestingSessionLocal = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(task_tracking, "SessionLocal", TestingSessionLocal)
    return TestingSessionLocal


def _fake_task(name: str, headers: dict[str, object] | None = None, args: list[object] | None = None) -> FakeTask:
    """Return a minimal task object exposing the request attributes used by signal handlers."""
    return FakeTask(name=name, headers=headers, args=args)


def test_task_execution_model_enforces_unique_task_id(db_session: Session) -> None:
    """Tracked executions should keep one row per Celery task id."""
    first = CeleryTaskExecution(
        task_id="duplicate-id",
        task_name=RUN_PROVISIONER_TASK,
        status="PENDING",
        queued_at=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
    )
    second = CeleryTaskExecution(
        task_id="duplicate-id",
        task_name=RUN_PROVISIONER_TASK,
        status="SUCCESS",
        queued_at=datetime(2026, 5, 5, 12, 1, tzinfo=timezone.utc),
    )

    db_session.add(first)
    db_session.commit()

    db_session.add(second)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_task_tracking_signals_record_publish_start_success(
    db_session: Session,
    tracking_session_factory,
) -> None:
    """Publishing and running a task should persist its happy-path lifecycle."""
    before_task_publish.send(
        sender=RUN_PROVISIONER_TASK,
        headers={
            "id": "task-success",
            "task": RUN_PROVISIONER_TASK,
            task_tracking.RESOURCE_TYPE_HEADER: "provisioner",
            task_tracking.RESOURCE_ID_HEADER: 12,
        },
        body=([12], {}, {}),
    )

    db_session.expire_all()
    execution = db_session.query(CeleryTaskExecution).filter(CeleryTaskExecution.task_id == "task-success").one()
    assert execution.status == "PENDING"
    assert execution.resource_type == "provisioner"
    assert execution.resource_id == 12
    assert execution.queued_at is not None

    task = _fake_task(
        RUN_PROVISIONER_TASK,
        headers={
            task_tracking.RESOURCE_TYPE_HEADER: "provisioner",
            task_tracking.RESOURCE_ID_HEADER: 12,
        },
        args=[12],
    )
    task_prerun.send(sender=task, task_id="task-success", task=task, args=[12], kwargs={})
    task_postrun.send(
        sender=task,
        task_id="task-success",
        task=task,
        args=[12],
        kwargs={},
        state="SUCCESS",
        retval={"created": 1, "updated": 0},
    )

    db_session.expire_all()
    execution = db_session.query(CeleryTaskExecution).filter(CeleryTaskExecution.task_id == "task-success").one()
    assert execution.status == "SUCCESS"
    assert execution.started_at is not None
    assert execution.finished_at is not None
    assert execution.duration_seconds is not None
    assert execution.duration_seconds >= 0
    assert execution.result == {"created": 1, "updated": 0}
    assert execution.error is None


def test_provider_machine_tasks_track_provider_resource_and_machine_result(
    db_session: Session,
    tracking_session_factory,
) -> None:
    """Machine-level provider tasks should stay grouped under their provider resource."""
    task = _fake_task(RUN_PROVIDER_MACHINE_TASK, args=[12, 34])

    task_prerun.send(sender=task, task_id="provider-machine-success", task=task, args=[12, 34], kwargs={})
    task_postrun.send(
        sender=task,
        task_id="provider-machine-success",
        task=task,
        args=[12, 34],
        kwargs={},
        state="SUCCESS",
        retval={"provider_id": 12, "machine_id": 34, "created": 1, "updated": 0, "skipped": 0},
    )

    db_session.expire_all()
    execution = (
        db_session.query(CeleryTaskExecution)
        .filter(CeleryTaskExecution.task_id == "provider-machine-success")
        .one()
    )
    assert execution.status == "SUCCESS"
    assert execution.resource_type == "provider"
    assert execution.resource_id == 12
    assert execution.result == {"provider_id": 12, "machine_id": 34, "created": 1, "updated": 0, "skipped": 0}


def test_task_tracking_signals_record_failure_and_prerun_fallback(
    db_session: Session,
    tracking_session_factory,
) -> None:
    """A task should be created on prerun fallback and capture terminal failures."""
    task = _fake_task(SYNC_APPLICATION_METRICS_TASK, args=[42])

    task_prerun.send(sender=task, task_id="task-failure", task=task, args=[42], kwargs={})
    task_failure.send(
        sender=task,
        task_id="task-failure",
        exception=ValueError("sync exploded"),
        args=[42],
        kwargs={},
        traceback=None,
        einfo=None,
    )
    task_postrun.send(
        sender=task,
        task_id="task-failure",
        task=task,
        args=[42],
        kwargs={},
        state="FAILURE",
        retval=None,
    )

    db_session.expire_all()
    execution = db_session.query(CeleryTaskExecution).filter(CeleryTaskExecution.task_id == "task-failure").one()
    assert execution.status == "FAILURE"
    assert execution.resource_type == "application"
    assert execution.resource_id == 42
    assert execution.started_at is not None
    assert execution.finished_at is not None
    assert execution.error == "sync exploded"


def test_task_tracking_signals_record_retry(db_session: Session, tracking_session_factory) -> None:
    """Retry signals should persist the intermediate retry state and error message."""
    task = _fake_task(SYNC_APPLICATION_METRICS_TASK, args=[7])
    request = SimpleNamespace(id="task-retry", args=[7])

    task_prerun.send(sender=task, task_id="task-retry", task=task, args=[7], kwargs={})
    task_retry.send(sender=task, request=request, reason=RuntimeError("try again later"))

    db_session.expire_all()
    execution = db_session.query(CeleryTaskExecution).filter(CeleryTaskExecution.task_id == "task-retry").one()
    assert execution.status == "RETRY"
    assert execution.resource_type == "application"
    assert execution.resource_id == 7
    assert execution.error == "try again later"


def test_worker_tasks_endpoint_filters_orders_and_paginates(client: TestClient, db_session: Session) -> None:
    """The task history endpoint should support documented filters and pagination."""
    db_session.add_all(
        [
            CeleryTaskExecution(
                task_id="task-1",
                task_name=RUN_PROVISIONER_TASK,
                status="SUCCESS",
                resource_type="provisioner",
                resource_id=1,
                queued_at=datetime(2026, 5, 5, 10, 0, tzinfo=timezone.utc),
                started_at=datetime(2026, 5, 5, 10, 1, tzinfo=timezone.utc),
                finished_at=datetime(2026, 5, 5, 10, 2, tzinfo=timezone.utc),
                duration_seconds=60,
                result={"created": 1},
            ),
            CeleryTaskExecution(
                task_id="task-2",
                task_name=RUN_PROVISIONER_TASK,
                status="FAILURE",
                resource_type="provisioner",
                resource_id=1,
                queued_at=datetime(2026, 5, 5, 11, 0, tzinfo=timezone.utc),
                error="boom",
            ),
            CeleryTaskExecution(
                task_id="task-3",
                task_name=SYNC_APPLICATION_METRICS_TASK,
                status="SUCCESS",
                resource_type="application",
                resource_id=2,
                queued_at=datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc),
                result={"synced": 1},
            ),
        ]
    )
    db_session.commit()

    response = client.get(
        "/v1/worker/tasks",
        params={
            "task_name": RUN_PROVISIONER_TASK,
            "resource_type": "provisioner",
            "resource_id": 1,
            "offset": 0,
            "limit": 1,
        },
    )
    assert response.status_code == 200
    assert response.json()["offset"] == 0
    assert response.json()["limit"] == 1
    assert response.json()["total"] == 2
    assert response.json()["items"][0]["task_id"] == "task-2"
    assert response.json()["items"][0]["status"] == "FAILURE"

    filtered = client.get(
        "/v1/worker/tasks",
        params={
            "task_name": RUN_PROVISIONER_TASK,
            "status": "SUCCESS",
            "resource_type": "provisioner",
            "resource_id": 1,
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["task_id"] == "task-1"


def test_manual_task_endpoints_return_202_and_create_tracking_rows(
    client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    tracking_session_factory,
) -> None:
    """Manual enqueue endpoints should keep returning task ids and seed task history."""
    application = Application(name="catalog", environment="prod", region="eu")
    platform = Platform(name="Tracked Platform")
    provisioner = MachineProvisioner(
        platform=platform,
        name="tracked inventory",
        type="capsule",
        enabled=True,
        cron="* * * * *",
        config={"token": "secret"},
    )
    provider = MachineProvider(
        platform=platform,
        name="tracked provider",
        type="prometheus",
        scope="cpu",
        enabled=True,
        config={"url": "https://prometheus.example", "query": "avg(up)"},
    )
    db_session.add_all([application, provisioner, provider])
    db_session.commit()

    task_ids = iter(
        [
            "manual-application-inventory-sync",
            "manual-application-metrics-dispatch",
            "manual-provider-sync-dispatch",
            "manual-provisioner-run",
        ]
    )

    def fake_send_task(
        task_name: str,
        args: list[object] | None = None,
        kwargs: dict[str, object] | None = None,
        headers: dict[str, object] | None = None,
    ) -> SimpleNamespace:
        """Simulate Celery task publication while preserving tracking side effects."""
        task_id = next(task_ids)
        publish_headers = {"id": task_id, "task": task_name, **(headers or {})}
        before_task_publish.send(sender=task_name, headers=publish_headers, body=(args or [], kwargs or {}, {}))
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr("internal.infra.queue.enqueue.celery_app.send_task", fake_send_task)

    inventory_sync_response = client.post("/v1/applications/sync", params={"type": "inventory_discovery"})
    metrics_sync_response = client.post("/v1/applications/sync", params={"type": "metrics"})
    provider_sync_response = client.post("/v1/machines/providers/sync")
    provisioner_response = client.post(f"/v1/machines/provisioners/{provisioner.id}/run")

    assert inventory_sync_response.status_code == 202
    assert inventory_sync_response.json() == {"task_id": "manual-application-inventory-sync"}
    assert metrics_sync_response.status_code == 202
    assert metrics_sync_response.json() == {"task_id": "manual-application-metrics-dispatch"}
    assert provider_sync_response.status_code == 202
    assert provider_sync_response.json() == {"task_id": "manual-provider-sync-dispatch"}
    assert provisioner_response.status_code == 202
    assert provisioner_response.json() == {"task_id": "manual-provisioner-run"}

    db_session.expire_all()
    rows = (
        db_session.query(CeleryTaskExecution)
        .order_by(CeleryTaskExecution.task_id.asc())
        .all()
    )
    assert [(row.task_id, row.task_name, row.status, row.resource_type, row.resource_id) for row in rows] == [
        (
            "manual-application-inventory-sync",
            SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK,
            "PENDING",
            None,
            None,
        ),
        (
            "manual-application-metrics-dispatch",
            DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK,
            "PENDING",
            None,
            None,
        ),
        (
            "manual-provider-sync-dispatch",
            DISPATCH_ENABLED_PROVIDER_SYNCS_TASK,
            "PENDING",
            None,
            None,
        ),
        ("manual-provisioner-run", RUN_PROVISIONER_TASK, "PENDING", "provisioner", provisioner.id),
    ]
