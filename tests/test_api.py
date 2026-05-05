"""End-to-end API tests for the FastAPI surface."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from internal.infra.db.models import MachineProvider


def test_swagger_is_served_on_root(client: TestClient) -> None:
    """Swagger UI should be served from the root path."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "SwaggerUIBundle" in response.text
    assert "/openapi.json" in response.text


def test_default_docs_endpoints_are_disabled(client: TestClient) -> None:
    """Default FastAPI docs routes should remain disabled."""
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_openapi_json_remains_available(client: TestClient) -> None:
    """The OpenAPI document should remain available for tooling."""
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Metrics Collector"
    schemas = response.json()["components"]["schemas"]
    assert "provisioner_ids" not in schemas["PrometheusProviderUpdate"]["properties"]
    assert "provisioner_ids" not in schemas["DynatraceProviderUpdate"]["properties"]


def test_typed_provisioner_routes_hide_config(client: TestClient) -> None:
    """Typed provisioner routes should never expose raw config or tokens."""
    platform = client.post("/platforms", json={"name": "VMWare"}).json()

    capsule = client.post(
        "/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "capsule inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    ).json()
    assert capsule["type"] == "capsule"
    assert capsule["has_token"] is True
    assert "token" not in capsule
    assert "config" not in capsule

    generic = client.get(f"/provisioners/{capsule['id']}").json()
    assert generic["type"] == "capsule"
    assert "config" not in generic

    patched_capsule = client.patch(
        f"/provisioners/{capsule['id']}/capsule",
        json={"name": "capsule inventory v2"},
    ).json()
    assert patched_capsule["name"] == "capsule inventory v2"
    assert patched_capsule["has_token"] is True

    dynatrace = client.post(
        "/provisioners/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace inventory",
            "url": "https://dynatrace.example",
            "token": "dynatrace-secret",
            "cron": "* * * * *",
        },
    ).json()
    assert dynatrace["type"] == "dynatrace"
    assert dynatrace["url"] == "https://dynatrace.example/"
    assert dynatrace["has_token"] is True
    assert "token" not in dynatrace

    wrong_route = client.get(f"/provisioners/{capsule['id']}/dynatrace")
    assert wrong_route.status_code == 404


def test_typed_provider_routes_hide_config_and_map_scope(client: TestClient, db_session: Session) -> None:
    """Typed provider routes should hide config and resolve public scopes."""
    platform = client.post("/platforms", json={"name": "Monitoring"}).json()
    provisioner = client.post(
        "/provisioners/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "inventory",
            "url": "https://inventory.example",
            "token": "inventory-secret",
            "cron": "* * * * *",
        },
    ).json()

    prometheus = client.post(
        "/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
            "provisioner_ids": [provisioner["id"]],
        },
    ).json()
    assert prometheus["type"] == "prometheus"
    assert prometheus["scope"] == "cpu"
    assert prometheus["provisioner_ids"] == [provisioner["id"]]
    assert "config" not in prometheus
    assert "metric_type_id" not in prometheus
    assert "cron" not in prometheus

    generic = client.get(f"/providers/{prometheus['id']}").json()
    assert generic["scope"] == "cpu"
    assert "config" not in generic
    assert "metric_type_id" not in generic
    assert "cron" not in generic

    specific = client.get(f"/providers/{prometheus['id']}/prometheus").json()
    assert specific["url"] == "https://prometheus.example/"
    assert specific["query"] == "avg(up)"

    patched = client.patch(
        f"/providers/{prometheus['id']}/prometheus",
        json={"scope": "ram", "query": "avg(node_memory_MemAvailable_bytes)"},
    ).json()
    assert patched["scope"] == "ram"
    assert patched["query"] == "avg(node_memory_MemAvailable_bytes)"

    provider_row = db_session.get(MachineProvider, prometheus["id"])
    assert provider_row is not None
    assert provider_row.metric_type.code == "ram"

    dynatrace = client.post(
        "/providers/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace disk",
            "scope": "disk",
            "url": "https://dynatrace.example",
            "token": "provider-secret",
            "provisioner_ids": [provisioner["id"]],
            "enabled": False,
        },
    ).json()
    assert dynatrace["type"] == "dynatrace"
    assert dynatrace["scope"] == "disk"
    assert dynatrace["has_token"] is True
    assert "token" not in dynatrace

    associated = client.get(f"/providers/{dynatrace['id']}/provisioners").json()
    assert associated[0]["id"] == provisioner["id"]

    wrong_route = client.get(f"/providers/{prometheus['id']}/dynatrace")
    assert wrong_route.status_code == 404

    detach = client.delete(f"/providers/{dynatrace['id']}/provisioners/{provisioner['id']}")
    assert detach.status_code == 204

    provider_after_detach = client.get(f"/providers/{dynatrace['id']}").json()
    assert provider_after_detach["provisioner_ids"] == []

    disabled_run = client.post(f"/providers/{dynatrace['id']}/run")
    assert disabled_run.status_code == 409
    assert disabled_run.json()["detail"] == "provider is disabled"


def test_provider_patch_ignores_provisioner_ids_and_validates_platform_change(client: TestClient) -> None:
    """Provider patch routes should ignore association payloads and keep platform checks."""
    platform = client.post("/platforms", json={"name": "Primary Monitoring"}).json()
    other_platform = client.post("/platforms", json={"name": "Secondary Monitoring"}).json()
    provisioner = client.post(
        "/provisioners/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "inventory",
            "url": "https://inventory.example",
            "token": "inventory-secret",
            "cron": "* * * * *",
        },
    ).json()

    prometheus = client.post(
        "/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
            "provisioner_ids": [provisioner["id"]],
        },
    ).json()
    dynatrace = client.post(
        "/providers/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace disk",
            "scope": "disk",
            "url": "https://dynatrace.example",
            "token": "provider-secret",
            "provisioner_ids": [provisioner["id"]],
        },
    ).json()

    patched_prometheus = client.patch(
        f"/providers/{prometheus['id']}/prometheus",
        json={
            "scope": "ram",
            "query": "avg(node_memory_MemAvailable_bytes)",
            "provisioner_ids": [],
        },
    )
    assert patched_prometheus.status_code == 200
    assert patched_prometheus.json()["scope"] == "ram"
    assert patched_prometheus.json()["query"] == "avg(node_memory_MemAvailable_bytes)"
    assert patched_prometheus.json()["provisioner_ids"] == [provisioner["id"]]

    patched_dynatrace = client.patch(
        f"/providers/{dynatrace['id']}/dynatrace",
        json={
            "enabled": False,
            "token": "provider-secret-v2",
            "provisioner_ids": [],
        },
    )
    assert patched_dynatrace.status_code == 200
    assert patched_dynatrace.json()["enabled"] is False
    assert patched_dynatrace.json()["has_token"] is True
    assert patched_dynatrace.json()["provisioner_ids"] == [provisioner["id"]]

    incompatible_platform_patch = client.patch(
        f"/providers/{prometheus['id']}/prometheus",
        json={"platform_id": other_platform["id"]},
    )
    assert incompatible_platform_patch.status_code == 400
    assert incompatible_platform_patch.json()["detail"] == "provider and provisioners must belong to the same platform"


def test_application_crud_and_machine_application_id(client: TestClient) -> None:
    """Applications should stay manageable through CRUD endpoints."""
    application = client.post(
        "/applications",
        json={"name": "billing", "environment": "prod", "region": "eu-west-1"},
    ).json()
    platform = client.post("/platforms", json={"name": "Application platform"}).json()

    machine = client.post(
        "/machines",
        json={
            "platform_id": platform["id"],
            "application_id": application["id"],
            "hostname": "billing-01",
        },
    ).json()

    assert machine["application_id"] == application["id"]

    listed = client.get("/applications", params={"environment": "prod", "region": "eu-west-1"}).json()
    assert listed[0]["name"] == "billing"

    patched = client.patch(f"/applications/{application['id']}", json={"region": "eu-west-2"}).json()
    assert patched["region"] == "eu-west-2"


def test_machine_crud_and_flavor_history_endpoint(client: TestClient) -> None:
    """Machines should expose CRUD and flavor history routes."""
    platform = client.post("/platforms", json={"name": "Proxmox"}).json()
    machine = client.post(
        "/machines",
        json={
            "platform_id": platform["id"],
            "hostname": "node-01",
            "region": "eu",
            "environment": "dev",
            "cpu": 2,
            "ram_gb": 8,
            "disk_gb": 80,
        },
    ).json()

    patched = client.patch(f"/machines/{machine['id']}", json={"environment": "prod"}).json()
    assert patched["environment"] == "prod"

    history = client.get(f"/machines/{machine['id']}/flavor-history").json()
    assert history == []
