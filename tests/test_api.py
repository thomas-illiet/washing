"""End-to-end API tests for the FastAPI surface."""

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from internal.infra.db.models import (
    Machine,
    MachineCPUMetric,
    MachineDiskMetric,
    MachineFlavorHistory,
    MachineProvider,
    MachineProvisioner,
    Platform,
)


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
    paths = response.json()["paths"]
    assert "provisioner_ids" not in schemas["PrometheusProviderUpdate"]["properties"]
    assert "provisioner_ids" not in schemas["DynatraceProviderUpdate"]["properties"]
    assert "/metric-types" not in paths
    assert "/metrics/{metric_name}" not in paths
    assert "/providers" not in paths
    assert "/providers/{provider_id}" not in paths
    assert "/providers/{provider_id}/provisioners" not in paths
    assert "/provisioners" not in paths
    assert "/provisioners/{provisioner_id}" not in paths
    assert "/providers/{provider_id}/run" not in paths
    assert "/machines/metrics" in paths
    assert "/machines/{machine_id}/metrics" in paths
    assert "/machines/providers" in paths
    assert "/machines/providers/{provider_id}" in paths
    assert "/machines/providers/{provider_id}/provisioners" in paths
    assert "/machines/provisioners" in paths
    assert "/machines/provisioners/{provisioner_id}" in paths
    assert "/machines/provisioners/{provisioner_id}/run" in paths
    assert "/tasks" in paths
    assert {"type", "offset", "limit"} <= {param["name"] for param in paths["/machines/metrics"]["get"]["parameters"]}
    assert {"type", "offset", "limit"} <= {
        param["name"] for param in paths["/machines/{machine_id}/metrics"]["get"]["parameters"]
    }


def test_typed_provisioner_routes_hide_config(client: TestClient) -> None:
    """Typed provisioner routes should never expose raw config or tokens."""
    platform = client.post("/platforms", json={"name": "VMWare"}).json()

    capsule = client.post(
        "/machines/provisioners/capsule",
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

    generic = client.get(f"/machines/provisioners/{capsule['id']}").json()
    assert generic["type"] == "capsule"
    assert "config" not in generic

    patched_capsule = client.patch(
        f"/machines/provisioners/{capsule['id']}/capsule",
        json={"name": "capsule inventory v2"},
    ).json()
    assert patched_capsule["name"] == "capsule inventory v2"
    assert patched_capsule["has_token"] is True

    dynatrace = client.post(
        "/machines/provisioners/dynatrace",
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

    wrong_route = client.get(f"/machines/provisioners/{capsule['id']}/dynatrace")
    assert wrong_route.status_code == 404


def test_typed_provider_routes_hide_config_and_map_scope(client: TestClient, db_session: Session) -> None:
    """Typed provider routes should hide config and resolve public scopes."""
    platform = client.post("/platforms", json={"name": "Monitoring"}).json()
    provisioner = client.post(
        "/machines/provisioners/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "inventory",
            "url": "https://inventory.example",
            "token": "inventory-secret",
            "cron": "* * * * *",
        },
    ).json()

    prometheus = client.post(
        "/machines/providers/prometheus",
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

    generic = client.get(f"/machines/providers/{prometheus['id']}").json()
    assert generic["scope"] == "cpu"
    assert "config" not in generic
    assert "metric_type_id" not in generic
    assert "cron" not in generic

    specific = client.get(f"/machines/providers/{prometheus['id']}/prometheus").json()
    assert specific["url"] == "https://prometheus.example/"
    assert specific["query"] == "avg(up)"

    patched = client.patch(
        f"/machines/providers/{prometheus['id']}/prometheus",
        json={"scope": "ram", "query": "avg(node_memory_MemAvailable_bytes)"},
    ).json()
    assert patched["scope"] == "ram"
    assert patched["query"] == "avg(node_memory_MemAvailable_bytes)"

    provider_row = db_session.get(MachineProvider, prometheus["id"])
    assert provider_row is not None
    assert provider_row.scope == "ram"

    dynatrace = client.post(
        "/machines/providers/dynatrace",
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

    associated = client.get(f"/machines/providers/{dynatrace['id']}/provisioners").json()
    assert associated[0]["id"] == provisioner["id"]

    wrong_route = client.get(f"/machines/providers/{prometheus['id']}/dynatrace")
    assert wrong_route.status_code == 404

    detach = client.delete(f"/machines/providers/{dynatrace['id']}/provisioners/{provisioner['id']}")
    assert detach.status_code == 204

    provider_after_detach = client.get(f"/machines/providers/{dynatrace['id']}").json()
    assert provider_after_detach["provisioner_ids"] == []

    disabled_run = client.post(f"/machines/providers/{dynatrace['id']}/run")
    assert disabled_run.status_code == 404


def test_provider_creation_rejects_duplicate_type_for_same_provisioner(client: TestClient) -> None:
    """A provisioner should not accept two attached providers of the same type."""
    platform = client.post("/platforms", json={"name": "Constraint Platform"}).json()
    provisioner = client.post(
        "/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    ).json()

    first_provider = client.post(
        "/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
            "provisioner_ids": [provisioner["id"]],
        },
    )
    assert first_provider.status_code == 201

    duplicate_type = client.post(
        "/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom ram",
            "scope": "ram",
            "url": "https://prometheus.example",
            "query": "avg(node_memory_MemAvailable_bytes)",
            "provisioner_ids": [provisioner["id"]],
        },
    )
    assert duplicate_type.status_code == 409
    assert duplicate_type.json()["detail"] == "provisioner cannot have more than one provider of the same type"

    providers = client.get("/machines/providers", params={"platform_id": platform["id"]}).json()
    assert [provider["name"] for provider in providers] == ["prom cpu"]

    other_type = client.post(
        "/machines/providers/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace cpu",
            "scope": "cpu",
            "url": "https://dynatrace.example",
            "token": "provider-secret",
            "provisioner_ids": [provisioner["id"]],
        },
    )
    assert other_type.status_code == 201


def test_provider_attach_rejects_duplicate_type_for_same_provisioner(client: TestClient) -> None:
    """Attaching a second provider of the same type should fail with a conflict."""
    platform = client.post("/platforms", json={"name": "Attach Constraint Platform"}).json()
    provisioner = client.post(
        "/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    ).json()

    first_provider = client.post(
        "/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom one",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    ).json()
    second_provider = client.post(
        "/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom two",
            "scope": "ram",
            "url": "https://prometheus.example",
            "query": "avg(node_memory_MemAvailable_bytes)",
        },
    ).json()

    first_attach = client.post(f"/machines/providers/{first_provider['id']}/provisioners/{provisioner['id']}")
    assert first_attach.status_code == 200

    second_attach = client.post(f"/machines/providers/{second_provider['id']}/provisioners/{provisioner['id']}")
    assert second_attach.status_code == 409
    assert second_attach.json()["detail"] == "provisioner cannot have more than one provider of the same type"

    detached_provider = client.get(f"/machines/providers/{second_provider['id']}").json()
    assert detached_provider["provisioner_ids"] == []


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


def test_machine_flavor_history_returns_changed_state_only(client: TestClient, db_session: Session) -> None:
    """Flavor history should expose only the changed state in CPU and MB units."""
    platform = Platform(name="Flavor History")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        hostname="node-01",
        cpu=2,
        ram_gb=8,
        disk_gb=80,
    )
    db_session.add_all([platform, provisioner, machine])
    db_session.commit()

    db_session.add(
        MachineFlavorHistory(
            machine_id=machine.id,
            source_provisioner_id=provisioner.id,
            cpu=4,
            ram_mb=16384,
            disk_mb=122880,
        )
    )
    db_session.commit()

    history = client.get(f"/machines/{machine.id}/flavor-history")
    assert history.status_code == 200
    assert history.json()[0]["machine_id"] == machine.id
    assert history.json()[0]["source_provisioner_id"] == provisioner.id
    assert history.json()[0]["cpu"] == 4
    assert history.json()[0]["ram_mb"] == 16384
    assert history.json()[0]["disk_mb"] == 122880
    assert "previous_cpu" not in history.json()[0]
    assert "previous_ram_gb" not in history.json()[0]
    assert "previous_disk_gb" not in history.json()[0]
    assert "new_cpu" not in history.json()[0]
    assert "new_ram_gb" not in history.json()[0]
    assert "new_disk_gb" not in history.json()[0]


def test_machine_metric_history_endpoint_requires_type_and_paginates(client: TestClient, db_session: Session) -> None:
    """Machine metric history should require a type and expose offset pagination."""
    platform = Platform(name="Machine Metrics")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(platform=platform, source_provisioner=provisioner, hostname="node-01")
    provider = MachineProvider(
        platform=platform,
        name="cpu provider",
        type="prometheus",
        scope="cpu",
        config={"url": "https://prometheus.example", "query": "avg(up)"},
        provisioners=[provisioner],
    )
    db_session.add_all([platform, provisioner, machine, provider])
    db_session.commit()

    db_session.add_all(
        [
            MachineCPUMetric(provider_id=provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=10),
            MachineCPUMetric(provider_id=provider.id, machine_id=machine.id, date=date(2026, 5, 2), value=20),
        ]
    )
    db_session.commit()

    missing_type = client.get(f"/machines/{machine.id}/metrics")
    assert missing_type.status_code == 422

    first_page = client.get(
        f"/machines/{machine.id}/metrics",
        params={"type": "cpu", "offset": 0, "limit": 1},
    )
    assert first_page.status_code == 200
    assert first_page.json()["offset"] == 0
    assert first_page.json()["limit"] == 1
    assert first_page.json()["total"] == 2
    assert first_page.json()["items"][0]["provider_id"] == provider.id
    assert first_page.json()["items"][0]["machine_id"] == machine.id
    assert first_page.json()["items"][0]["date"] == "2026-05-02"
    assert first_page.json()["items"][0]["value"] == 20
    assert "created_at" not in first_page.json()["items"][0]
    assert "updated_at" not in first_page.json()["items"][0]

    second_page = client.get(
        f"/machines/{machine.id}/metrics",
        params={"type": "cpu", "offset": 1, "limit": 1},
    )
    assert second_page.status_code == 200
    assert second_page.json()["total"] == 2
    assert second_page.json()["items"][0]["date"] == "2026-05-01"
    assert second_page.json()["items"][0]["value"] == 10

    missing_machine = client.get("/machines/9999/metrics", params={"type": "cpu"})
    assert missing_machine.status_code == 404
    assert missing_machine.json()["detail"] == "machine not found"


def test_machine_metrics_global_endpoint_filters_and_paginates(client: TestClient, db_session: Session) -> None:
    """Global machine metrics should paginate and support the documented filters."""
    platform = Platform(name="Global Metrics")
    other_platform = Platform(name="Other Metrics")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    other_provisioner = MachineProvisioner(
        platform=other_platform,
        name="other inventory",
        type="mock_inventory",
        cron="* * * * *",
    )
    machine_one = Machine(platform=platform, source_provisioner=provisioner, hostname="node-01")
    machine_two = Machine(platform=platform, source_provisioner=provisioner, hostname="node-02")
    other_machine = Machine(platform=other_platform, source_provisioner=other_provisioner, hostname="node-03")
    provider = MachineProvider(
        platform=platform,
        name="cpu provider",
        type="prometheus",
        scope="cpu",
        config={"url": "https://prometheus.example", "query": "avg(up)"},
        provisioners=[provisioner],
    )
    other_provider = MachineProvider(
        platform=other_platform,
        name="other cpu provider",
        type="prometheus",
        scope="cpu",
        config={"url": "https://prometheus.example", "query": "avg(up)"},
        provisioners=[other_provisioner],
    )
    db_session.add_all(
        [
            platform,
            other_platform,
            provisioner,
            other_provisioner,
            machine_one,
            machine_two,
            other_machine,
            provider,
            other_provider,
        ]
    )
    db_session.commit()

    db_session.add_all(
        [
            MachineCPUMetric(provider_id=provider.id, machine_id=machine_one.id, date=date(2026, 5, 1), value=10),
            MachineCPUMetric(provider_id=provider.id, machine_id=machine_one.id, date=date(2026, 5, 2), value=20),
            MachineCPUMetric(provider_id=provider.id, machine_id=machine_two.id, date=date(2026, 5, 3), value=30),
            MachineDiskMetric(provider_id=provider.id, machine_id=machine_two.id, date=date(2026, 5, 3), value=40),
            MachineCPUMetric(
                provider_id=other_provider.id,
                machine_id=other_machine.id,
                date=date(2026, 5, 3),
                value=50,
            ),
        ]
    )
    db_session.commit()

    missing_type = client.get("/machines/metrics")
    assert missing_type.status_code == 422

    invalid_type = client.get("/machines/metrics", params={"type": "gpu"})
    assert invalid_type.status_code == 422

    response = client.get(
        "/machines/metrics",
        params={
            "type": "cpu",
            "platform_id": platform.id,
            "provider_id": provider.id,
            "provisioner_id": provisioner.id,
            "start": "2026-05-02",
            "end": "2026-05-03",
            "offset": 0,
            "limit": 1,
        },
    )
    assert response.status_code == 200
    assert response.json()["offset"] == 0
    assert response.json()["limit"] == 1
    assert response.json()["total"] == 2
    assert response.json()["items"][0]["machine_id"] == machine_two.id
    assert response.json()["items"][0]["date"] == "2026-05-03"
    assert response.json()["items"][0]["value"] == 30
    assert "created_at" not in response.json()["items"][0]
    assert "updated_at" not in response.json()["items"][0]

    filtered_machine = client.get(
        "/machines/metrics",
        params={
            "type": "cpu",
            "machine_id": machine_one.id,
            "offset": 0,
            "limit": 10,
        },
    )
    assert filtered_machine.status_code == 200
    assert filtered_machine.json()["total"] == 2
    assert [item["date"] for item in filtered_machine.json()["items"]] == ["2026-05-02", "2026-05-01"]
