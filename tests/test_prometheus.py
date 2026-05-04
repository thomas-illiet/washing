from types import SimpleNamespace

from celery.signals import beat_init, task_postrun, task_prerun, worker_ready, worker_shutdown
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from internal.infra.observability import prometheus as prometheus_module


class DummyTask:
    name = "tests.dummy_task"


def test_api_prometheus_endpoint_exposes_http_metrics(client: TestClient) -> None:
    health_response = client.get("/health")
    assert health_response.status_code == 200

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]

    body = response.text
    assert "api_http_requests_total" in body
    assert 'route="/health"' in body


def test_celery_prometheus_signals_record_task_metrics() -> None:
    prometheus_module.configure_celery_prometheus()
    task = DummyTask()

    task_prerun.send(sender=task, task_id="prometheus-test-task", task=task)
    task_postrun.send(sender=task, task_id="prometheus-test-task", task=task, state="SUCCESS")

    body = generate_latest().decode()
    assert "celery_tasks_total" in body
    assert 'task_name="tests.dummy_task"' in body
    assert 'state="SUCCESS"' in body


def test_celery_prometheus_runtime_liveness_metrics(monkeypatch) -> None:
    started_ports: list[int] = []

    monkeypatch.setattr(
        prometheus_module,
        "get_settings",
        lambda: SimpleNamespace(celery_prometheus_enabled=True, celery_prometheus_port=9101),
    )
    monkeypatch.setattr(prometheus_module, "start_http_server", lambda port: started_ports.append(port))
    monkeypatch.setattr(prometheus_module, "_CELERY_METRICS_SERVER_STARTED", False)

    prometheus_module.CELERY_WORKER_UP.set(0)
    prometheus_module.CELERY_BEAT_UP.set(0)
    prometheus_module.configure_celery_prometheus()

    worker_ready.send(sender="tests.worker")
    beat_init.send(sender="tests.beat")
    worker_shutdown.send(sender="tests.worker")

    body = generate_latest().decode()
    assert started_ports == [9101]
    assert "celery_worker_up 0.0" in body
    assert "celery_beat_up 1.0" in body
