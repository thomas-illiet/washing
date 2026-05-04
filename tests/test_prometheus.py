from celery.signals import task_postrun, task_prerun
from fastapi.testclient import TestClient
from prometheus_client import generate_latest

from internal.infra.observability.prometheus import configure_celery_prometheus


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
    configure_celery_prometheus()
    task = DummyTask()

    task_prerun.send(sender=task, task_id="prometheus-test-task", task=task)
    task_postrun.send(sender=task, task_id="prometheus-test-task", task=task, state="SUCCESS")

    body = generate_latest().decode()
    assert "celery_tasks_total" in body
    assert 'task_name="tests.dummy_task"' in body
    assert 'state="SUCCESS"' in body
