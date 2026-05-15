"""End-to-end API tests for the FastAPI surface."""

from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from internal.domain.cron import INVALID_CRON_EXPRESSION_DETAIL
from internal.infra.config.settings import get_settings
from internal.infra.db.models import (
    Application,
    CeleryTaskExecution,
    Machine,
    MachineCPUMetric,
    MachineDiskMetric,
    MachineFlavorHistory,
    MachineProvider,
    MachineProvisioner,
    MachineRAMMetric,
    MachineOptimization,
    Platform,
)
from internal.infra.queue.task_names import (
    DISPATCH_DUE_MACHINE_PROVISIONER_JOBS_TASK,
    RUN_PROVIDER_TASK,
    SYNC_APPLICATION_METRICS_TASK,
)
from internal.usecases.inventory import run_provisioner_inventory
from internal.usecases.applications import rebuild_applications_from_machines
from internal.usecases.optimizations import refresh_machine_optimization

EXPECTED_OPENAPI_DESCRIPTION = (
    "Inventory and machine metrics API for platforms, applications, providers, and provisioners.\n\n"
    "Use this documentation to browse collection endpoints, operational actions, and async worker tasks."
)

EXPECTED_OPENAPI_TAG_DESCRIPTIONS = {
    "Platforms": "Cycle programs and settings.",
    "Applications": "Loads to track in the drum.",
    "Discovery": "Assistant-ready inventory and optimization discovery.",
    "Machines": "Main drum and inventory.",
    "Machine Optimizations": "Current machine capacity recommendations.",
    "Machine Metrics": "CPU, RAM, and disk spin cycle.",
    "Machine Providers": "Water inlets and metric sources.",
    "Machine Provisioners": "Detergent drawers and inventory connectors.",
    "Tasks": "Asynchronous porthole queue.",
}


def _response_schema_name(operation: dict) -> str:
    """Resolve the OpenAPI schema name used by a response model."""
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    return schema["$ref"].rpartition("/")[2]


def _assert_paginated_list_route(body: dict, path: str) -> None:
    """Assert that a list route exposes the shared pagination contract."""
    operation = body["paths"][path]["get"]
    assert {"offset", "limit"} <= {param["name"] for param in operation["parameters"]}
    schema_name = _response_schema_name(operation)
    assert schema_name.startswith("PaginatedResponse_")
    schema = body["components"]["schemas"][schema_name]
    assert {"items", "offset", "limit", "total"} <= set(schema["properties"])


def _persist_machine(db_session: Session, **values) -> Machine:
    """Create a machine row directly in the test database."""
    machine = Machine(**values)
    db_session.add(machine)
    db_session.commit()
    db_session.refresh(machine)
    return machine


def _assert_invalid_cron_response(body: dict) -> None:
    """Assert the FastAPI validation payload for an invalid cron expression."""
    detail = body["detail"][0]
    assert detail["loc"][-1] == "cron"
    assert detail["msg"].endswith(INVALID_CRON_EXPRESSION_DETAIL)


def test_swagger_is_served_on_root(client: TestClient) -> None:
    """Swagger UI should be served from the root path."""
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "SwaggerUIBundle" in response.text
    assert "/v1/openapi.json" in response.text
    assert "/static/swagger-washing-machine.css" in response.text
    assert "/static/swagger-tag-images/machines.png" in response.text
    assert '"defaultModelsExpandDepth": -1' in response.text


def test_swagger_theme_css_is_served(client: TestClient) -> None:
    """The custom Swagger theme stylesheet should be served as a static asset."""
    response = client.get("/static/swagger-washing-machine.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert "--wm-bg: #f6fbfd;" in response.text
    assert "discovery.png" in response.text
    assert "machine-optimizations.png" in response.text
    scheme_container_rule = response.text.split(".swagger-ui .scheme-container {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    assert "backdrop-filter" not in scheme_container_rule


def test_discovery_swagger_tag_image_is_served(client: TestClient) -> None:
    """The Discovery tag artwork should be available to the Swagger theme."""
    response = client.get("/static/swagger-tag-images/discovery.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content.startswith(b"\x89PNG")


def test_default_docs_endpoints_are_disabled(client: TestClient) -> None:
    """Default FastAPI docs routes should remain disabled."""
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_openapi_json_remains_available(client: TestClient) -> None:
    """The OpenAPI document should remain available for tooling."""
    response = client.get("/v1/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == get_settings().app_name
    assert response.json()["info"]["description"] == EXPECTED_OPENAPI_DESCRIPTION
    body = response.json()
    schemas = body["components"]["schemas"]
    paths = body["paths"]
    tag_descriptions = {tag["name"]: tag.get("description") for tag in body["tags"]}
    tags = [tag["name"] for tag in body["tags"]]
    assert "name" not in schemas["PlatformUpdate"]["properties"]
    assert "PlatformSummaryRead" in schemas
    assert "DiscoveryCatalogRead" in schemas
    assert "ApplicationOverviewRead" in schemas
    assert "MachineContextRead" in schemas
    assert "OptimizationRecommendationRead" in schemas
    assert "DiscoveryRecordRead" in schemas
    assert "ApplicationCreate" not in schemas
    assert "ApplicationUpdate" not in schemas
    assert {"sync_at", "sync_scheduled_at", "sync_error"} <= set(schemas["ApplicationRead"]["properties"])
    assert "extra" not in schemas["ApplicationRead"]["properties"]
    assert "application" in schemas["MachineRead"]["properties"]
    assert "application_id" not in schemas["MachineRead"]["properties"]
    assert {"cpu", "ram", "disk"} <= set(schemas["MachineMetricLatestRead"]["properties"])
    optimization_properties = set(schemas["MachineOptimizationRead"]["properties"])
    assert {"resources"} <= optimization_properties
    assert not {
        "revision",
        "is_current",
        "acknowledged_at",
        "acknowledged_by",
        "window_size",
        "details",
        "current_cpu",
        "current_ram_mb",
        "current_disk_mb",
        "target_cpu",
        "target_ram_mb",
        "target_disk_mb",
    } & optimization_properties
    assert "enabled" not in schemas["CapsuleProvisionerCreate"]["properties"]
    assert "enabled" not in schemas["CapsuleProvisionerUpdate"]["properties"]
    assert "parameters" in schemas["CapsuleProvisionerCreate"]["properties"]
    assert "parameters" in schemas["CapsuleProvisionerUpdate"]["properties"]
    assert "parameters" in schemas["CapsuleProvisionerRead"]["properties"]
    assert "enabled" not in schemas["DynatraceProvisionerCreate"]["properties"]
    assert "enabled" not in schemas["DynatraceProvisionerUpdate"]["properties"]
    assert "MockProvisionerCreate" not in schemas
    assert "MockProvisionerUpdate" not in schemas
    assert "MockProvisionerRead" not in schemas
    assert "MockProviderCreate" not in schemas
    assert "MockProviderUpdate" not in schemas
    assert "MockProviderRead" not in schemas
    assert "enabled" not in schemas["PrometheusProviderCreate"]["properties"]
    assert "provisioner_ids" not in schemas["PrometheusProviderCreate"]["properties"]
    assert "provisioner_ids" not in schemas["PrometheusProviderUpdate"]["properties"]
    assert "enabled" not in schemas["PrometheusProviderUpdate"]["properties"]
    assert "enabled" not in schemas["DynatraceProviderCreate"]["properties"]
    assert "provisioner_ids" not in schemas["DynatraceProviderUpdate"]["properties"]
    assert "enabled" not in schemas["DynatraceProviderUpdate"]["properties"]
    assert "/metric-types" not in paths
    assert "/metrics/{metric_name}" not in paths
    assert "/providers" not in paths
    assert "/providers/{provider_id}" not in paths
    assert "/providers/{provider_id}/provisioners" not in paths
    assert "/provisioners" not in paths
    assert "/provisioners/{provisioner_id}" not in paths
    assert "/providers/{provider_id}/run" not in paths
    assert "/health" not in paths
    assert "/v1/platforms/{platform_id}/summary" in paths
    assert "/v1/discovery/catalog" in paths
    assert "/v1/discovery/applications" in paths
    assert "/v1/discovery/applications/{application_id}/overview" in paths
    assert "/v1/discovery/machines/search" in paths
    assert "/v1/discovery/machines/{machine_id}/context" in paths
    assert "/v1/discovery/optimizations/current" in paths
    assert "/v1/discovery/records/{record_id}" in paths
    assert "/v1/machines/metrics" in paths
    assert "/v1/machines/{machine_id}/metrics" in paths
    assert "/v1/machines/{machine_id}/metrics/latest" in paths
    assert "/v1/machines/{machine_id}" in paths
    assert "/v1/machines/optimizations" in paths
    assert "/v1/machines/optimizations/{optimization_id}/acknowledge" not in paths
    assert "/v1/machines/{machine_id}/optimizations" in paths
    assert "/v1/machines/{machine_id}/optimizations/history" not in paths
    assert "/v1/machines/{machine_id}/optimizations/recalculate" in paths
    assert "/v1/machines/providers" in paths
    assert "/v1/machines/providers/{provider_id}" in paths
    assert "/v1/machines/providers/sync" in paths
    assert "/v1/machines/providers/{provider_id}/enable" in paths
    assert "/v1/machines/providers/{provider_id}/disable" in paths
    assert "/v1/machines/providers/{provider_id}/run" in paths
    assert "/v1/machines/providers/{provider_id}/machines" in paths
    assert "/v1/machines/providers/{provider_id}/provisioners" in paths
    assert "/v1/machines/providers/mock" not in paths
    assert "/v1/machines/providers/{provider_id}/mock" not in paths
    assert "/v1/machines/provisioners" in paths
    assert "/v1/machines/provisioners/sync" in paths
    assert "/v1/machines/provisioners/{provisioner_id}" in paths
    assert "/v1/machines/provisioners/{provisioner_id}/machines" in paths
    assert "/v1/machines/provisioners/{provisioner_id}/providers" in paths
    assert "/v1/machines/provisioners/mock" not in paths
    assert "/v1/machines/provisioners/{provisioner_id}/mock" not in paths
    assert "/v1/machines/provisioners/{provisioner_id}/enable" in paths
    assert "/v1/machines/provisioners/{provisioner_id}/disable" in paths
    assert "/v1/machines/provisioners/{provisioner_id}/run" in paths
    assert "/v1/applications/sync" in paths
    assert "/v1/applications/{application_id}/machines" in paths
    assert "/v1/applications/{application_id}/metrics/sync" in paths
    assert "/v1/applications/{application_id}/optimizations" in paths
    assert "/v1/worker/tasks" in paths
    assert "/v1/worker/tasks/{task_id}" in paths
    assert "Health" not in tags
    assert tags == list(EXPECTED_OPENAPI_TAG_DESCRIPTIONS)
    assert tag_descriptions == EXPECTED_OPENAPI_TAG_DESCRIPTIONS
    assert tags.index("Applications") < tags.index("Discovery")
    assert tags.index("Discovery") < tags.index("Machines")
    assert tags.index("Machines") < tags.index("Machine Optimizations")
    assert tags.index("Machine Optimizations") < tags.index("Machine Metrics")
    assert tags.index("Machine Metrics") < tags.index("Machine Providers")
    assert tags.index("Machine Providers") < tags.index("Machine Provisioners")
    assert paths["/v1/machines"]["get"]["tags"] == ["Machines"]
    assert paths["/v1/discovery/catalog"]["get"]["tags"] == ["Discovery"]
    assert paths["/v1/discovery/applications"]["get"]["tags"] == ["Discovery"]
    assert paths["/v1/discovery/machines/search"]["get"]["tags"] == ["Discovery"]
    assert paths["/v1/discovery/optimizations/current"]["get"]["tags"] == ["Discovery"]
    assert paths["/v1/discovery/records/{record_id}"]["get"]["tags"] == ["Discovery"]
    assert "post" not in paths["/v1/machines"]
    assert paths["/v1/machines/{machine_id}"]["get"]["tags"] == ["Machines"]
    assert paths["/v1/machines/{machine_id}"]["delete"]["tags"] == ["Machines"]
    assert "patch" not in paths["/v1/machines/{machine_id}"]
    assert paths["/v1/machines/{machine_id}/flavor-history"]["get"]["tags"] == ["Machines"]
    assert paths["/v1/machines/optimizations"]["get"]["tags"] == ["Machine Optimizations"]
    assert paths["/v1/machines/{machine_id}/optimizations"]["get"]["tags"] == ["Machine Optimizations"]
    assert paths["/v1/machines/{machine_id}/optimizations/recalculate"]["post"]["tags"] == [
        "Machine Optimizations"
    ]
    assert paths["/v1/machines/metrics"]["get"]["tags"] == ["Machine Metrics"]
    assert paths["/v1/machines/{machine_id}/metrics"]["get"]["tags"] == ["Machine Metrics"]
    assert paths["/v1/machines/{machine_id}/metrics/latest"]["get"]["tags"] == ["Machine Metrics"]
    assert paths["/v1/machines/providers"]["get"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/providers/sync"]["post"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/providers/{provider_id}/enable"]["post"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/providers/{provider_id}/run"]["post"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/providers/{provider_id}/machines"]["get"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/providers/{provider_id}/prometheus"]["get"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/providers/{provider_id}/provisioners"]["get"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/provisioners"]["get"]["tags"] == ["Machine Provisioners"]
    assert paths["/v1/machines/provisioners/sync"]["post"]["tags"] == ["Machine Provisioners"]
    assert paths["/v1/machines/provisioners/{provisioner_id}/enable"]["post"]["tags"] == ["Machine Provisioners"]
    assert paths["/v1/machines/provisioners/{provisioner_id}/machines"]["get"]["tags"] == ["Machine Provisioners"]
    assert paths["/v1/machines/provisioners/{provisioner_id}/providers"]["get"]["tags"] == ["Machine Provisioners"]
    assert paths["/v1/machines/provisioners/{provisioner_id}/dynatrace"]["get"]["tags"] == ["Machine Provisioners"]
    assert paths["/v1/machines/provisioners/{provisioner_id}/run"]["post"]["tags"] == ["Machine Provisioners"]
    assert paths["/v1/applications/sync"]["post"]["tags"] == ["Applications"]
    assert paths["/v1/applications/{application_id}/machines"]["get"]["tags"] == ["Applications"]
    assert paths["/v1/applications/{application_id}/metrics/sync"]["post"]["tags"] == ["Applications"]
    assert paths["/v1/applications/{application_id}/optimizations"]["get"]["tags"] == ["Applications"]
    assert {param["name"] for param in paths["/v1/applications/sync"]["post"]["parameters"]} == {"type"}
    sync_responses = paths["/v1/applications/sync"]["post"]["responses"]
    assert "202" in sync_responses
    assert (
        sync_responses["202"]["content"]["application/json"]["schema"]["$ref"].rpartition("/")[2]
        == "TaskEnqueueResponse"
    )
    assert "post" not in paths["/v1/applications"]
    assert "delete" not in paths["/v1/applications/{application_id}"]
    assert "patch" not in paths["/v1/applications/{application_id}"]
    for path in [
        "/v1/platforms",
        "/v1/applications",
        "/v1/machines",
        "/v1/machines/{machine_id}/flavor-history",
        "/v1/machines/optimizations",
        "/v1/machines/metrics",
        "/v1/machines/{machine_id}/metrics",
        "/v1/machines/providers",
        "/v1/machines/providers/{provider_id}/machines",
        "/v1/machines/providers/{provider_id}/provisioners",
        "/v1/machines/provisioners",
        "/v1/machines/provisioners/{provisioner_id}/machines",
        "/v1/machines/provisioners/{provisioner_id}/providers",
        "/v1/applications/{application_id}/machines",
        "/v1/applications/{application_id}/optimizations",
        "/v1/worker/tasks",
    ]:
        _assert_paginated_list_route(body, path)
    assert {"type", "offset", "limit"} <= {param["name"] for param in paths["/v1/machines/metrics"]["get"]["parameters"]}
    assert {"type", "offset", "limit"} <= {
        param["name"] for param in paths["/v1/machines/{machine_id}/metrics"]["get"]["parameters"]
    }
    assert {
        "platform_id",
        "machine_id",
        "application",
        "environment",
        "region",
        "status",
        "action",
        "offset",
        "limit",
    } <= {param["name"] for param in paths["/v1/machines/optimizations"]["get"]["parameters"]}
    optimization_responses = paths["/v1/machines/{machine_id}/optimizations/recalculate"]["post"]["responses"]
    assert "202" in optimization_responses
    assert (
        optimization_responses["202"]["content"]["application/json"]["schema"]["$ref"].rpartition("/")[2]
        == "TaskEnqueueResponse"
    )
    assert "202" in paths["/v1/machines/provisioners/sync"]["post"]["responses"]
    assert "202" in paths["/v1/machines/providers/{provider_id}/run"]["post"]["responses"]
    assert "202" in paths["/v1/applications/{application_id}/metrics/sync"]["post"]["responses"]


def test_platform_list_is_paginated_and_stably_sorted(client: TestClient) -> None:
    """Platforms should return the shared paginated envelope with a stable sort."""
    empty = client.get("/v1/platforms")
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "offset": 0, "limit": 100, "total": 0}

    client.post("/v1/platforms", json={"name": "VMWare"})
    client.post("/v1/platforms", json={"name": "AWS"})

    first_page = client.get("/v1/platforms", params={"offset": 0, "limit": 1})
    assert first_page.status_code == 200
    assert first_page.json()["offset"] == 0
    assert first_page.json()["limit"] == 1
    assert first_page.json()["total"] == 2
    assert [item["name"] for item in first_page.json()["items"]] == ["AWS"]

    second_page = client.get("/v1/platforms", params={"offset": 1, "limit": 1})
    assert second_page.status_code == 200
    assert second_page.json()["total"] == 2
    assert [item["name"] for item in second_page.json()["items"]] == ["VMWare"]

    beyond_total = client.get("/v1/platforms", params={"offset": 5, "limit": 1})
    assert beyond_total.status_code == 200
    assert beyond_total.json()["total"] == 2
    assert beyond_total.json()["items"] == []


def test_platform_patch_cannot_update_name(client: TestClient) -> None:
    """Platform patch should allow metadata updates but reject renames."""
    platform = client.post(
        "/v1/platforms",
        json={"name": "VMWare", "description": "Initial description", "extra": {"team": "ops"}},
    ).json()

    patch_description = client.patch(
        f"/v1/platforms/{platform['id']}",
        json={"description": "Updated description", "extra": {"team": "platform"}},
    )
    assert patch_description.status_code == 200
    assert patch_description.json()["name"] == "VMWare"
    assert patch_description.json()["description"] == "Updated description"
    assert patch_description.json()["extra"] == {"team": "platform"}

    patch_name = client.patch(
        f"/v1/platforms/{platform['id']}",
        json={"name": "AWS"},
    )
    assert patch_name.status_code == 422


def test_platform_summary_counts_inventory_connectors_and_current_optimizations(
    client: TestClient,
    db_session: Session,
) -> None:
    """Platform summary should aggregate the platform-owned data only."""
    platform = client.post("/v1/platforms", json={"name": "Summary Platform"}).json()
    other_platform = Platform(name="Summary Other")
    provisioner = MachineProvisioner(
        platform_id=platform["id"],
        name="enabled inventory",
        type="mock_inventory",
        enabled=True,
        cron="* * * * *",
    )
    disabled_provisioner = MachineProvisioner(
        platform_id=platform["id"],
        name="disabled inventory",
        type="mock_inventory",
        enabled=False,
        cron="* * * * *",
    )
    provider = MachineProvider(
        platform_id=platform["id"],
        name="enabled cpu",
        type="prometheus",
        scope="cpu",
        enabled=True,
        config={"url": "https://prometheus.example", "query": "avg(up)"},
    )
    disabled_provider = MachineProvider(
        platform_id=platform["id"],
        name="disabled ram",
        type="prometheus",
        scope="ram",
        enabled=False,
        config={"url": "https://prometheus.example", "query": "avg(mem)"},
    )
    machine_one = Machine(
        platform_id=platform["id"],
        source_provisioner=provisioner,
        hostname="summary-01",
        application="checkout",
        environment="prod",
        region="eu",
    )
    machine_two = Machine(
        platform_id=platform["id"],
        source_provisioner=provisioner,
        hostname="summary-02",
        application="CHECKOUT",
        environment="PROD",
        region="EU",
    )
    other_machine = Machine(platform=other_platform, hostname="summary-other", application="billing")
    db_session.add_all(
        [
            other_platform,
            provisioner,
            disabled_provisioner,
            provider,
            disabled_provider,
            machine_one,
            machine_two,
            other_machine,
        ]
    )
    db_session.flush()
    db_session.add(
        MachineOptimization(
            machine_id=machine_one.id,
            status="ready",
            action="scale_up",
            window_size=30,
            min_cpu=1,
            max_cpu=64,
            min_ram_mb=2048,
            max_ram_mb=262144,
            current_cpu=2,
            current_ram_mb=4096,
            current_disk_mb=51200,
            target_cpu=4,
            target_ram_mb=4096,
            target_disk_mb=51200,
            details={},
        )
    )
    db_session.commit()

    response = client.get(f"/v1/platforms/{platform['id']}/summary")

    assert response.status_code == 200
    assert response.json() == {
        "platform_id": platform["id"],
        "machines": 2,
        "applications": 1,
        "providers": 2,
        "enabled_providers": 1,
        "provisioners": 2,
        "enabled_provisioners": 1,
        "current_optimizations": 1,
        "current_optimizations_by_status": {"ready": 1},
        "current_optimizations_by_action": {"scale_up": 1},
    }

    missing = client.get("/v1/platforms/9999/summary")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "platform not found"


def test_discovery_endpoints_expose_assistant_ready_context(client: TestClient, db_session: Session) -> None:
    """Discovery routes should expose bounded application, machine, and optimization context."""
    platform = client.post("/v1/platforms", json={"name": "Discovery Platform"}).json()
    billing_machine = _persist_machine(
        db_session,
        platform_id=platform["id"],
        application="billing",
        hostname="billing-01",
        external_id="vm-billing-01",
        environment="prod",
        region="eu-west-1",
        cpu=2,
        ram_mb=4096,
        disk_mb=51200,
    )
    _persist_machine(
        db_session,
        platform_id=platform["id"],
        application="catalog",
        hostname="catalog-01",
        environment="dev",
        region="us-east-1",
    )
    rebuild_applications_from_machines(db_session)
    billing_application = db_session.query(Application).filter(Application.name == "BILLING").one()
    provider = MachineProvider(
        platform_id=platform["id"],
        name="discovery cpu",
        type="prometheus",
        scope="cpu",
        enabled=True,
        config={"url": "https://prometheus.example", "query": "cpu"},
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add_all(
        [
            MachineCPUMetric(
                provider_id=provider.id,
                machine_id=billing_machine.id,
                date=date(2026, 5, 1),
                value=91,
            ),
            MachineOptimization(
                machine_id=billing_machine.id,
                status="ready",
                action="scale_up",
                window_size=30,
                min_cpu=1,
                max_cpu=64,
                min_ram_mb=2048,
                max_ram_mb=262144,
                current_cpu=2,
                current_ram_mb=4096,
                current_disk_mb=51200,
                target_cpu=4,
                target_ram_mb=4096,
                target_disk_mb=51200,
                details={
                    "cpu": {
                        "status": "ok",
                        "action": "scale_up",
                        "utilization_percent": 91,
                        "reason_code": "pressure_high",
                    },
                    "ram": {
                        "status": "ok",
                        "action": "keep",
                        "utilization_percent": 55,
                        "reason_code": "pressure_normal",
                    },
                    "disk": {
                        "status": "ok",
                        "action": "keep",
                        "utilization_percent": 40,
                        "reason_code": "pressure_normal",
                    },
                },
            ),
        ]
    )
    db_session.commit()

    catalog = client.get("/v1/discovery/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["environments"] == ["DEV", "PROD"]
    assert catalog.json()["regions"] == ["EU-WEST-1", "US-EAST-1"]
    assert catalog.json()["metric_types"] == ["cpu", "ram", "disk"]
    assert catalog.json()["totals"]["applications"] == 2
    assert catalog.json()["totals"]["current_optimizations"] == 1

    applications = client.get("/v1/discovery/applications", params={"max_results": 1})
    assert applications.status_code == 200
    assert applications.json()["total"] == 2
    assert applications.json()["returned"] == 1
    assert applications.json()["truncated"] is True

    billing_summary = client.get("/v1/discovery/applications", params={"name": "billing"}).json()["items"][0]
    assert billing_summary["application"]["id"] == billing_application.id
    assert billing_summary["machine_count"] == 1
    assert billing_summary["platform_ids"] == [platform["id"]]
    assert billing_summary["current_optimization_count"] == 1
    assert billing_summary["current_optimizations_by_action"] == {"scale_up": 1}

    overview = client.get(
        f"/v1/discovery/applications/{billing_application.id}/overview",
        params={"max_machines": 1, "max_optimizations": 1},
    )
    assert overview.status_code == 200
    assert overview.json()["application"]["name"] == "BILLING"
    assert overview.json()["machines"]["items"][0]["hostname"] == "BILLING-01"
    assert overview.json()["current_optimizations"]["items"][0]["action"] == "scale_up"

    machine_search = client.get("/v1/discovery/machines/search", params={"q": "billing"})
    assert machine_search.status_code == 200
    assert machine_search.json()["total"] == 1
    assert machine_search.json()["items"][0]["external_id"] == "vm-billing-01"

    context = client.get(f"/v1/discovery/machines/{billing_machine.id}/context")
    assert context.status_code == 200
    assert context.json()["application"]["id"] == billing_application.id
    assert context.json()["latest_metrics"]["cpu"]["value"] == 91
    assert context.json()["current_optimization"]["resources"]["cpu"]["recommended"] == 4

    recommendations = client.get("/v1/discovery/optimizations/current", params={"action": "scale_up"})
    assert recommendations.status_code == 200
    assert recommendations.json()["items"][0]["machine"]["hostname"] == "BILLING-01"
    assert recommendations.json()["items"][0]["application"]["name"] == "BILLING"

    record = client.get(f"/v1/discovery/records/application:{billing_application.id}")
    assert record.status_code == 200
    assert record.json()["id"] == f"application:{billing_application.id}"
    assert record.json()["metadata"]["name"] == "BILLING"
    assert '"machine_count": 1' in record.json()["text"]


def test_named_fields_reject_blank_strings(client: TestClient) -> None:
    """Business identifiers should reject blank or whitespace-only strings."""
    assert client.post("/v1/platforms", json={"name": "   "}).status_code == 422

    platform = client.post("/v1/platforms", json={"name": "Validation Platform"}).json()
    assert (
        client.post(
            "/v1/machines/provisioners/capsule",
            json={"platform_id": platform["id"], "name": "   ", "token": "capsule-secret"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/v1/machines/providers/prometheus",
            json={
                "platform_id": platform["id"],
                "name": "prom cpu",
                "scope": "cpu",
                "url": "https://prometheus.example",
                "query": "   ",
            },
        ).status_code
        == 422
    )


def test_application_routes_are_read_only_and_sync_type_is_validated(client: TestClient) -> None:
    """Application writes should stay disabled while sync inputs stay constrained."""
    create_response = client.post(
        "/v1/applications",
        json={"name": "billing", "environment": "prod", "region": "eu-west-1"},
    )
    assert create_response.status_code == 405

    invalid_sync_response = client.post("/v1/applications/sync", params={"type": "invalid"})
    assert invalid_sync_response.status_code == 422


def test_typed_integration_routes_require_existing_platforms(client: TestClient, dev_client: TestClient) -> None:
    """Typed provider and provisioner routes should 404 on missing platforms."""
    provisioner_response = client.post(
        "/v1/machines/provisioners/capsule",
        json={"platform_id": 999, "name": "inventory", "token": "capsule-secret"},
    )
    assert provisioner_response.status_code == 404
    assert provisioner_response.json()["detail"] == "platform not found"

    provider_response = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": 999,
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    )
    assert provider_response.status_code == 404
    assert provider_response.json()["detail"] == "platform not found"

    mock_provider_response = dev_client.post(
        "/v1/machines/providers/mock",
        json={"platform_id": 999, "name": "mock cpu", "scope": "cpu"},
    )
    assert mock_provider_response.status_code == 404
    assert mock_provider_response.json()["detail"] == "platform not found"


def test_typed_provisioner_routes_hide_config(client: TestClient, db_session: Session) -> None:
    """Typed provisioner routes should never expose raw config or tokens."""
    platform = client.post("/v1/platforms", json={"name": "VMWare"}).json()

    capsule = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "capsule inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
            "parameters": {"tenant": "prod", "region": "eu-west-3"},
        },
    ).json()
    assert capsule["type"] == "capsule"
    assert capsule["enabled"] is False
    assert capsule["has_token"] is True
    assert capsule["parameters"] == {"tenant": "prod", "region": "eu-west-3"}
    assert "token" not in capsule
    assert "config" not in capsule

    provisioner = db_session.get(MachineProvisioner, capsule["id"])
    assert provisioner is not None
    assert provisioner.config["parameters"] == {"tenant": "prod", "region": "eu-west-3"}

    generic = client.get(f"/v1/machines/provisioners/{capsule['id']}").json()
    assert generic["type"] == "capsule"
    assert "config" not in generic

    typed_capsule = client.get(f"/v1/machines/provisioners/{capsule['id']}/capsule").json()
    assert typed_capsule["parameters"] == {"tenant": "prod", "region": "eu-west-3"}

    patched_capsule = client.patch(
        f"/v1/machines/provisioners/{capsule['id']}/capsule",
        json={"name": "capsule inventory v2"},
    ).json()
    assert patched_capsule["name"] == "capsule inventory v2"
    assert patched_capsule["has_token"] is True
    assert patched_capsule["parameters"] == {"tenant": "prod", "region": "eu-west-3"}

    dynatrace = client.post(
        "/v1/machines/provisioners/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace inventory",
            "url": "https://dynatrace.example",
            "token": "dynatrace-secret",
            "cron": "* * * * *",
        },
    ).json()
    assert dynatrace["type"] == "dynatrace"
    assert dynatrace["enabled"] is False
    assert dynatrace["url"] == "https://dynatrace.example/"
    assert dynatrace["has_token"] is True
    assert "token" not in dynatrace

    wrong_route = client.get(f"/v1/machines/provisioners/{capsule['id']}/dynatrace")
    assert wrong_route.status_code == 404


def test_mock_provisioner_routes_are_absent_outside_dev(client: TestClient) -> None:
    """Production mode should not register the typed mock provisioner routes."""
    platform = client.post("/v1/platforms", json={"name": "Prod Mock Hidden"}).json()
    response = client.post(
        "/v1/machines/provisioners/mock",
        json={"platform_id": platform["id"], "name": "mock inventory"},
    )
    assert response.status_code == 405


def test_mock_provider_routes_are_absent_outside_dev(client: TestClient) -> None:
    """Production mode should not register the typed mock provider routes."""
    platform = client.post("/v1/platforms", json={"name": "Prod Mock Provider Hidden"}).json()
    response = client.post(
        "/v1/machines/providers/mock",
        json={"platform_id": platform["id"], "name": "mock cpu", "scope": "cpu"},
    )
    assert response.status_code == 405


def test_dev_openapi_includes_mock_provisioner_routes(dev_client: TestClient) -> None:
    """Development mode should expose the mock typed provisioner in OpenAPI."""
    response = dev_client.get("/v1/openapi.json")

    assert response.status_code == 200
    body = response.json()
    schemas = body["components"]["schemas"]
    paths = body["paths"]

    assert "MockProvisionerCreate" in schemas
    assert "MockProvisionerUpdate" in schemas
    assert "MockProvisionerRead" in schemas
    assert "/v1/machines/provisioners/mock" in paths
    assert "/v1/machines/provisioners/{provisioner_id}/mock" in paths
    assert paths["/v1/machines/provisioners/mock"]["post"]["tags"] == ["Machine Provisioners"]


def test_dev_openapi_includes_mock_provider_routes(dev_client: TestClient) -> None:
    """Development mode should expose the mock typed provider in OpenAPI."""
    response = dev_client.get("/v1/openapi.json")

    assert response.status_code == 200
    body = response.json()
    schemas = body["components"]["schemas"]
    paths = body["paths"]

    assert "MockProviderCreate" in schemas
    assert "MockProviderUpdate" in schemas
    assert "MockProviderRead" in schemas
    assert "enabled" not in schemas["MockProviderCreate"]["properties"]
    assert "provisioner_ids" not in schemas["MockProviderUpdate"]["properties"]
    assert "enabled" not in schemas["MockProviderUpdate"]["properties"]
    assert "provisioner_ids" not in schemas["MockProviderCreate"]["properties"]
    assert "value" not in schemas["MockProviderCreate"]["properties"]
    assert "values_by_hostname" not in schemas["MockProviderCreate"]["properties"]
    assert "value" not in schemas["MockProviderUpdate"]["properties"]
    assert "values_by_hostname" not in schemas["MockProviderUpdate"]["properties"]
    assert "provisioner_ids" not in schemas["MockProviderRead"]["properties"]
    assert "value" not in schemas["MockProviderRead"]["properties"]
    assert "values_by_hostname" not in schemas["MockProviderRead"]["properties"]
    assert "/v1/machines/providers/mock" in paths
    assert "/v1/machines/providers/{provider_id}/mock" in paths
    assert paths["/v1/machines/providers/mock"]["post"]["tags"] == ["Machine Providers"]


def test_dev_mock_provisioner_routes_use_json_presets(dev_client: TestClient) -> None:
    """Development mode should expose a typed mock provisioner backed by presets."""
    platform = dev_client.post("/v1/platforms", json={"name": "Mock Platform"}).json()

    created = dev_client.post(
        "/v1/machines/provisioners/mock",
        json={
            "platform_id": platform["id"],
            "name": "mock inventory",
            "cron": "*/15 * * * *",
        },
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["type"] == "mock"
    assert created_body["preset"] == "single-vm"
    assert created_body["cron"] == "*/15 * * * *"
    assert created_body["enabled"] is False
    assert "config" not in created_body

    fetched = dev_client.get(f"/v1/machines/provisioners/{created_body['id']}/mock")
    assert fetched.status_code == 200
    assert fetched.json()["preset"] == "single-vm"

    patched = dev_client.patch(
        f"/v1/machines/provisioners/{created_body['id']}/mock",
        json={"name": "mock inventory v2", "preset": "small-fleet"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "mock inventory v2"
    assert patched.json()["preset"] == "small-fleet"


def test_dev_mock_provider_routes_expose_mock_metric_config(dev_client: TestClient) -> None:
    """Development mode should expose a typed mock provider backed by mock_metric config."""
    platform = dev_client.post("/v1/platforms", json={"name": "Mock Metrics Platform"}).json()

    created = dev_client.post(
        "/v1/machines/providers/mock",
        json={
            "platform_id": platform["id"],
            "name": "mock cpu",
            "scope": "cpu",
        },
    )
    assert created.status_code == 201
    created_body = created.json()
    assert created_body["type"] == "mock_metric"
    assert created_body["scope"] == "cpu"
    assert created_body["enabled"] is False
    assert "config" not in created_body
    assert "provisioner_ids" not in created_body
    assert "value" not in created_body
    assert "values_by_hostname" not in created_body

    fetched = dev_client.get(f"/v1/machines/providers/{created_body['id']}/mock")
    assert fetched.status_code == 200
    assert "provisioner_ids" not in fetched.json()
    assert "value" not in fetched.json()
    assert "values_by_hostname" not in fetched.json()

    patched = dev_client.patch(
        f"/v1/machines/providers/{created_body['id']}/mock",
        json={"scope": "ram", "name": "mock ram"},
    )
    assert patched.status_code == 200
    assert patched.json()["scope"] == "ram"
    assert patched.json()["name"] == "mock ram"
    assert "provisioner_ids" not in patched.json()
    assert "value" not in patched.json()
    assert "values_by_hostname" not in patched.json()


def test_dev_mock_provisioner_routes_reject_unknown_preset(dev_client: TestClient) -> None:
    """Development mode should reject invalid or unknown mock presets."""
    platform = dev_client.post("/v1/platforms", json={"name": "Mock Validation"}).json()

    invalid_name = dev_client.post(
        "/v1/machines/provisioners/mock",
        json={"platform_id": platform["id"], "name": "mock inventory", "preset": "../escape"},
    )
    assert invalid_name.status_code == 400
    assert invalid_name.json()["detail"] == "invalid mock preset: ../escape"

    unknown = dev_client.post(
        "/v1/machines/provisioners/mock",
        json={"platform_id": platform["id"], "name": "mock inventory", "preset": "does-not-exist"},
    )
    assert unknown.status_code == 400
    assert unknown.json()["detail"] == "unknown mock preset: does-not-exist"


def test_typed_provisioner_routes_accept_valid_cron_on_create_and_update(client: TestClient) -> None:
    """Typed provisioner routes should accept valid cron expressions on writes."""
    platform = client.post("/v1/platforms", json={"name": "Cron Validation Success"}).json()

    capsule = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "capsule cron inventory",
            "token": "capsule-secret",
            "cron": "*/15 * * * *",
        },
    )
    assert capsule.status_code == 201
    assert capsule.json()["cron"] == "*/15 * * * *"

    capsule_update = client.patch(
        f"/v1/machines/provisioners/{capsule.json()['id']}/capsule",
        json={"cron": "0 * * * *"},
    )
    assert capsule_update.status_code == 200
    assert capsule_update.json()["cron"] == "0 * * * *"

    dynatrace = client.post(
        "/v1/machines/provisioners/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace cron inventory",
            "url": "https://dynatrace.example",
            "token": "dynatrace-secret",
            "cron": "*/10 * * * *",
        },
    )
    assert dynatrace.status_code == 201
    assert dynatrace.json()["cron"] == "*/10 * * * *"

    dynatrace_update = client.patch(
        f"/v1/machines/provisioners/{dynatrace.json()['id']}/dynatrace",
        json={"cron": "30 * * * *"},
    )
    assert dynatrace_update.status_code == 200
    assert dynatrace_update.json()["cron"] == "30 * * * *"


def test_typed_provisioner_routes_reject_invalid_cron_on_create_and_update(client: TestClient) -> None:
    """Typed provisioner routes should reject invalid cron expressions on writes."""
    platform = client.post("/v1/platforms", json={"name": "Cron Validation Failure"}).json()

    invalid_capsule_create = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "capsule invalid cron",
            "token": "capsule-secret",
            "cron": "not-a-cron",
        },
    )
    assert invalid_capsule_create.status_code == 422
    _assert_invalid_cron_response(invalid_capsule_create.json())

    capsule = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "capsule update cron",
            "token": "capsule-secret",
            "cron": "*/5 * * * *",
        },
    ).json()
    invalid_capsule_update = client.patch(
        f"/v1/machines/provisioners/{capsule['id']}/capsule",
        json={"cron": "not-a-cron"},
    )
    assert invalid_capsule_update.status_code == 422
    _assert_invalid_cron_response(invalid_capsule_update.json())

    invalid_dynatrace_create = client.post(
        "/v1/machines/provisioners/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace invalid cron",
            "url": "https://dynatrace.example",
            "token": "dynatrace-secret",
            "cron": "not-a-cron",
        },
    )
    assert invalid_dynatrace_create.status_code == 422
    _assert_invalid_cron_response(invalid_dynatrace_create.json())

    dynatrace = client.post(
        "/v1/machines/provisioners/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace update cron",
            "url": "https://dynatrace.example",
            "token": "dynatrace-secret",
            "cron": "*/5 * * * *",
        },
    ).json()
    invalid_dynatrace_update = client.patch(
        f"/v1/machines/provisioners/{dynatrace['id']}/dynatrace",
        json={"cron": "not-a-cron"},
    )
    assert invalid_dynatrace_update.status_code == 422
    _assert_invalid_cron_response(invalid_dynatrace_update.json())


def test_typed_provider_routes_hide_config_and_map_scope(client: TestClient, db_session: Session) -> None:
    """Typed provider routes should hide config and resolve public scopes."""
    platform = client.post("/v1/platforms", json={"name": "Monitoring"}).json()
    provisioner = client.post(
        "/v1/machines/provisioners/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "inventory",
            "url": "https://inventory.example",
            "token": "inventory-secret",
            "cron": "* * * * *",
        },
    ).json()

    prometheus = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    ).json()
    assert prometheus["type"] == "prometheus"
    assert prometheus["enabled"] is False
    assert prometheus["scope"] == "cpu"
    assert prometheus["provisioner_ids"] == []

    attach_prometheus = client.post(f"/v1/machines/providers/{prometheus['id']}/provisioners/{provisioner['id']}")
    assert attach_prometheus.status_code == 200
    assert attach_prometheus.json()["provisioner_ids"] == [provisioner["id"]]

    prometheus = client.get(f"/v1/machines/providers/{prometheus['id']}/prometheus").json()
    assert prometheus["provisioner_ids"] == [provisioner["id"]]
    assert "config" not in prometheus
    assert "metric_type_id" not in prometheus
    assert "cron" not in prometheus

    generic = client.get(f"/v1/machines/providers/{prometheus['id']}").json()
    assert generic["scope"] == "cpu"
    assert "config" not in generic
    assert "metric_type_id" not in generic
    assert "cron" not in generic

    specific = client.get(f"/v1/machines/providers/{prometheus['id']}/prometheus").json()
    assert specific["url"] == "https://prometheus.example/"
    assert specific["query"] == "avg(up)"

    patched = client.patch(
        f"/v1/machines/providers/{prometheus['id']}/prometheus",
        json={"scope": "ram", "query": "avg(node_memory_MemAvailable_bytes)"},
    ).json()
    assert patched["scope"] == "ram"
    assert patched["query"] == "avg(node_memory_MemAvailable_bytes)"

    provider_row = db_session.get(MachineProvider, prometheus["id"])
    assert provider_row is not None
    assert provider_row.scope == "ram"

    dynatrace = client.post(
        "/v1/machines/providers/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace disk",
            "scope": "disk",
            "url": "https://dynatrace.example",
            "token": "provider-secret",
            "provisioner_ids": [provisioner["id"]],
        },
    ).json()
    assert dynatrace["type"] == "dynatrace"
    assert dynatrace["enabled"] is False
    assert dynatrace["scope"] == "disk"
    assert dynatrace["has_token"] is True
    assert "token" not in dynatrace

    associated = client.get(f"/v1/machines/providers/{dynatrace['id']}/provisioners").json()
    assert associated["total"] == 1
    assert associated["items"][0]["id"] == provisioner["id"]

    wrong_route = client.get(f"/v1/machines/providers/{prometheus['id']}/dynatrace")
    assert wrong_route.status_code == 404

    detach = client.delete(f"/v1/machines/providers/{dynatrace['id']}/provisioners/{provisioner['id']}")
    assert detach.status_code == 204

    provider_after_detach = client.get(f"/v1/machines/providers/{dynatrace['id']}").json()
    assert provider_after_detach["provisioner_ids"] == []

    disabled_run = client.post(f"/v1/machines/providers/{dynatrace['id']}/run")
    assert disabled_run.status_code == 409
    assert disabled_run.json()["detail"] == "provider must be enabled before it can run"


def test_typed_integration_write_payloads_reject_enabled_field(client: TestClient) -> None:
    """Typed create and update payloads should reject public writes to enabled."""
    platform = client.post("/v1/platforms", json={"name": "Enable Validation"}).json()

    provisioner_create = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "capsule inventory",
            "token": "capsule-secret",
            "enabled": True,
        },
    )
    assert provisioner_create.status_code == 422

    provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "capsule inventory",
            "token": "capsule-secret",
        },
    ).json()

    provisioner_update = client.patch(
        f"/v1/machines/provisioners/{provisioner['id']}/capsule",
        json={"enabled": True},
    )
    assert provisioner_update.status_code == 422

    provider_create = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
            "enabled": True,
        },
    )
    assert provider_create.status_code == 422

    provider_with_provisioners_create = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu with provisioners",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
            "provisioner_ids": [provisioner["id"]],
        },
    )
    assert provider_with_provisioners_create.status_code == 422

    provider = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    ).json()

    provider_update = client.patch(
        f"/v1/machines/providers/{provider['id']}/prometheus",
        json={"enabled": True},
    )
    assert provider_update.status_code == 422


def test_capsule_parameters_patch_replaces_and_clears_dict(client: TestClient, db_session: Session) -> None:
    """Capsule parameters should be preserved, replaced, and clearable through PATCH."""
    platform = client.post("/v1/platforms", json={"name": "Capsule Parameters"}).json()
    provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "capsule inventory",
            "token": "capsule-secret",
            "parameters": {"tenant": "prod", "region": "eu-west-3"},
        },
    ).json()

    untouched = client.patch(
        f"/v1/machines/provisioners/{provisioner['id']}/capsule",
        json={"cron": "0 * * * *"},
    )
    assert untouched.status_code == 200
    assert untouched.json()["parameters"] == {"tenant": "prod", "region": "eu-west-3"}

    replaced = client.patch(
        f"/v1/machines/provisioners/{provisioner['id']}/capsule",
        json={"parameters": {"tenant": "staging"}},
    )
    assert replaced.status_code == 200
    assert replaced.json()["parameters"] == {"tenant": "staging"}

    db_session.expire_all()
    persisted = db_session.get(MachineProvisioner, provisioner["id"])
    assert persisted is not None
    assert persisted.config["parameters"] == {"tenant": "staging"}

    cleared = client.patch(
        f"/v1/machines/provisioners/{provisioner['id']}/capsule",
        json={"parameters": {}},
    )
    assert cleared.status_code == 200
    assert cleared.json()["parameters"] == {}

    db_session.expire_all()
    persisted = db_session.get(MachineProvisioner, provisioner["id"])
    assert persisted is not None
    assert persisted.config["parameters"] == {}


def test_provider_enable_disable_routes_are_idempotent(client: TestClient) -> None:
    """Provider enable/disable action endpoints should be idempotent and filterable."""
    platform = client.post("/v1/platforms", json={"name": "Provider Toggle Platform"}).json()
    provider = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    ).json()

    assert provider["enabled"] is False

    enabled = client.post(f"/v1/machines/providers/{provider['id']}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    enabled_again = client.post(f"/v1/machines/providers/{provider['id']}/enable")
    assert enabled_again.status_code == 200
    assert enabled_again.json()["enabled"] is True

    enabled_list = client.get(
        "/v1/machines/providers",
        params={"platform_id": platform["id"], "enabled": True},
    ).json()
    assert enabled_list["total"] == 1
    assert [item["name"] for item in enabled_list["items"]] == ["prom cpu"]

    disabled = client.post(f"/v1/machines/providers/{provider['id']}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    disabled_again = client.post(f"/v1/machines/providers/{provider['id']}/disable")
    assert disabled_again.status_code == 200
    assert disabled_again.json()["enabled"] is False

    disabled_list = client.get(
        "/v1/machines/providers",
        params={"platform_id": platform["id"], "enabled": False},
    ).json()
    assert disabled_list["total"] == 1
    assert [item["name"] for item in disabled_list["items"]] == ["prom cpu"]

    assert client.post("/v1/machines/providers/9999/enable").status_code == 404
    assert client.post("/v1/machines/providers/9999/disable").status_code == 404


def test_provisioner_enable_disable_routes_are_idempotent(client: TestClient) -> None:
    """Provisioner enable/disable action endpoints should be idempotent."""
    platform = client.post("/v1/platforms", json={"name": "Provisioner Toggle Platform"}).json()
    provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "inventory",
            "token": "capsule-secret",
        },
    ).json()

    assert provisioner["enabled"] is False

    enabled = client.post(f"/v1/machines/provisioners/{provisioner['id']}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    enabled_again = client.post(f"/v1/machines/provisioners/{provisioner['id']}/enable")
    assert enabled_again.status_code == 200
    assert enabled_again.json()["enabled"] is True

    disabled = client.post(f"/v1/machines/provisioners/{provisioner['id']}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    disabled_again = client.post(f"/v1/machines/provisioners/{provisioner['id']}/disable")
    assert disabled_again.status_code == 200
    assert disabled_again.json()["enabled"] is False

    assert client.post("/v1/machines/provisioners/9999/enable").status_code == 404
    assert client.post("/v1/machines/provisioners/9999/disable").status_code == 404


def test_manual_provisioner_run_rejects_disabled_provisioners(client: TestClient) -> None:
    """Manual run should require the provisioner to be enabled first."""
    platform = client.post("/v1/platforms", json={"name": "Manual Run Guard Platform"}).json()
    provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "inventory",
            "token": "capsule-secret",
        },
    ).json()

    response = client.post(f"/v1/machines/provisioners/{provisioner['id']}/run")
    assert response.status_code == 409
    assert response.json()["detail"] == "provisioner must be enabled before it can run"


def test_manual_provider_sync_rejects_when_no_provider_is_enabled(client: TestClient) -> None:
    """Global provider sync should fail fast when nothing can run."""
    platform = client.post("/v1/platforms", json={"name": "Manual Provider Sync Guard"}).json()
    client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    )

    response = client.post("/v1/machines/providers/sync")
    assert response.status_code == 409
    assert response.json()["detail"] == "at least one enabled provider is required before syncing machine metrics"


def test_manual_provider_sync_enqueues_global_dispatch(
    client: TestClient,
    monkeypatch,
) -> None:
    """Global provider sync should enqueue the provider dispatcher task."""
    platform = client.post("/v1/platforms", json={"name": "Manual Provider Sync"}).json()
    provider = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    ).json()
    enabled = client.post(f"/v1/machines/providers/{provider['id']}/enable")
    assert enabled.status_code == 200

    monkeypatch.setattr(
        "internal.infra.queue.enqueue.celery_app.send_task",
        lambda *args, **kwargs: SimpleNamespace(id="provider-sync-dispatch"),
    )

    response = client.post("/v1/machines/providers/sync")
    assert response.status_code == 202
    assert response.json() == {"task_id": "provider-sync-dispatch"}


def test_provider_run_and_visible_machines_endpoint(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """Provider run should enqueue one provider dispatcher and expose visible machines."""
    platform = client.post("/v1/platforms", json={"name": "Provider Run Platform"}).json()
    provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "provider run inventory",
            "token": "capsule-secret",
        },
    ).json()
    other_provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "provider run other inventory",
            "token": "capsule-secret",
        },
    ).json()
    provider = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "provider run cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    ).json()
    attach = client.post(f"/v1/machines/providers/{provider['id']}/provisioners/{provisioner['id']}")
    assert attach.status_code == 200

    db_session.add_all(
        [
            Machine(
                platform_id=platform["id"],
                source_provisioner_id=provisioner["id"],
                hostname="provider-visible-01",
            ),
            Machine(
                platform_id=platform["id"],
                source_provisioner_id=other_provisioner["id"],
                hostname="provider-hidden-01",
            ),
        ]
    )
    db_session.commit()

    machines = client.get(f"/v1/machines/providers/{provider['id']}/machines")
    assert machines.status_code == 200
    assert machines.json()["total"] == 1
    assert machines.json()["items"][0]["hostname"] == "PROVIDER-VISIBLE-01"

    disabled = client.post(f"/v1/machines/providers/{provider['id']}/run")
    assert disabled.status_code == 409
    assert disabled.json()["detail"] == "provider must be enabled before it can run"

    client.post(f"/v1/machines/providers/{provider['id']}/enable")
    sent_tasks = []

    def fake_send_task(task_name: str, *args, **kwargs) -> SimpleNamespace:
        sent_tasks.append(task_name)
        return SimpleNamespace(id="manual-provider-run")

    monkeypatch.setattr("internal.infra.queue.enqueue.celery_app.send_task", fake_send_task)
    run = client.post(f"/v1/machines/providers/{provider['id']}/run")
    assert run.status_code == 202
    assert run.json() == {"task_id": "manual-provider-run"}
    assert sent_tasks == [RUN_PROVIDER_TASK]

    assert client.get("/v1/machines/providers/9999/machines").status_code == 404
    assert client.post("/v1/machines/providers/9999/run").status_code == 404


def test_provider_creation_rejects_duplicate_scope_for_same_provisioner(client: TestClient) -> None:
    """A provisioner should not accept two attached providers for the same metric scope."""
    platform = client.post("/v1/platforms", json={"name": "Constraint Platform"}).json()
    provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    ).json()

    first_provider = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    )
    assert first_provider.status_code == 201
    first_attach = client.post(f"/v1/machines/providers/{first_provider.json()['id']}/provisioners/{provisioner['id']}")
    assert first_attach.status_code == 200

    second_scope = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom ram",
            "scope": "ram",
            "url": "https://prometheus.example",
            "query": "avg(node_memory_MemAvailable_bytes)",
        },
    )
    assert second_scope.status_code == 201
    second_attach = client.post(f"/v1/machines/providers/{second_scope.json()['id']}/provisioners/{provisioner['id']}")
    assert second_attach.status_code == 200

    providers = client.get("/v1/machines/providers", params={"platform_id": platform["id"]}).json()
    assert providers["total"] == 2
    assert [provider["name"] for provider in providers["items"]] == ["prom cpu", "prom ram"]

    duplicate_scope = client.post(
        "/v1/machines/providers/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace cpu",
            "scope": "cpu",
            "url": "https://dynatrace.example",
            "token": "provider-secret",
            "provisioner_ids": [provisioner["id"]],
        },
    )
    assert duplicate_scope.status_code == 409
    assert duplicate_scope.json()["detail"] == "provisioner cannot have more than one provider for the same scope"


def test_provider_attach_rejects_duplicate_scope_for_same_provisioner(client: TestClient) -> None:
    """Attaching a second provider for the same metric scope should fail with a conflict."""
    platform = client.post("/v1/platforms", json={"name": "Attach Constraint Platform"}).json()
    provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    ).json()

    first_provider = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom one",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    ).json()
    second_provider = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom two",
            "scope": "ram",
            "url": "https://prometheus.example",
            "query": "avg(node_memory_MemAvailable_bytes)",
        },
    ).json()
    third_provider = client.post(
        "/v1/machines/providers/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace cpu",
            "scope": "cpu",
            "url": "https://dynatrace.example",
            "token": "provider-secret",
        },
    ).json()

    first_attach = client.post(f"/v1/machines/providers/{first_provider['id']}/provisioners/{provisioner['id']}")
    assert first_attach.status_code == 200

    second_attach = client.post(f"/v1/machines/providers/{second_provider['id']}/provisioners/{provisioner['id']}")
    assert second_attach.status_code == 200

    third_attach = client.post(f"/v1/machines/providers/{third_provider['id']}/provisioners/{provisioner['id']}")
    assert third_attach.status_code == 409
    assert third_attach.json()["detail"] == "provisioner cannot have more than one provider for the same scope"

    detached_provider = client.get(f"/v1/machines/providers/{third_provider['id']}").json()
    assert detached_provider["provisioner_ids"] == []


def test_provider_update_rejects_duplicate_scope_for_attached_provisioner(
    client: TestClient,
    db_session: Session,
) -> None:
    """Updating a provider scope should fail when the target scope is already attached."""
    platform = client.post("/v1/platforms", json={"name": "Update Constraint Platform"}).json()
    provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    ).json()

    cpu_provider = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    ).json()
    attach = client.post(f"/v1/machines/providers/{cpu_provider['id']}/provisioners/{provisioner['id']}")
    assert attach.status_code == 200
    ram_provider = client.post(
        "/v1/machines/providers/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "dynatrace ram",
            "scope": "ram",
            "url": "https://dynatrace.example",
            "token": "provider-secret",
            "provisioner_ids": [provisioner["id"]],
        },
    ).json()

    response = client.patch(
        f"/v1/machines/providers/{ram_provider['id']}/dynatrace",
        json={"scope": "cpu"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "provisioner cannot have more than one provider for the same scope"

    provider_row = db_session.get(MachineProvider, ram_provider["id"])
    assert provider_row is not None
    assert provider_row.scope == "ram"


def test_application_projection_and_machine_application_field(client: TestClient, db_session: Session) -> None:
    """Applications should be discoverable from machine-owned application codes."""
    platform = client.post("/v1/platforms", json={"name": "Application platform"}).json()

    machine = _persist_machine(
        db_session,
        platform_id=platform["id"],
        application="billing",
        environment="PROD",
        region="EU-WEST-1",
        hostname="billing-01",
    )
    rebuild_applications_from_machines(db_session)

    fetched_machine = client.get(f"/v1/machines/{machine.id}")
    assert fetched_machine.status_code == 200
    assert fetched_machine.json()["application"] == "BILLING"

    listed = client.get("/v1/applications", params={"environment": "prod", "region": "eu-west-1"}).json()
    assert listed["total"] == 1
    assert listed["items"][0]["name"] == "BILLING"
    assert "extra" not in listed["items"][0]

    fetched = client.get(f"/v1/applications/{listed['items'][0]['id']}").json()
    assert fetched["region"] == "EU-WEST-1"
    assert "extra" not in fetched


def test_application_child_routes_list_machines_sync_metrics_and_optimizations(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """Application child endpoints should use the projection row as the lookup key."""
    platform = client.post("/v1/platforms", json={"name": "Application Child Routes"}).json()
    application = Application(name="checkout", environment="prod", region="eu")
    machine = Machine(
        platform_id=platform["id"],
        application="checkout",
        hostname="checkout-app-01",
        environment="prod",
        region="eu",
        cpu=2,
        ram_mb=4096,
        disk_mb=51200,
    )
    other_machine = Machine(
        platform_id=platform["id"],
        application="checkout",
        hostname="checkout-app-02",
        environment="dev",
        region="eu",
    )
    db_session.add_all([application, machine, other_machine])
    db_session.flush()
    optimization = MachineOptimization(
        machine_id=machine.id,
        status="ready",
        action="keep",
        window_size=30,
        min_cpu=1,
        max_cpu=64,
        min_ram_mb=2048,
        max_ram_mb=262144,
        computed_at=machine.updated_at,
        current_cpu=2,
        current_ram_mb=4096,
        current_disk_mb=51200,
        target_cpu=2,
        target_ram_mb=4096,
        target_disk_mb=51200,
        details={},
    )
    db_session.add(optimization)
    db_session.commit()

    machines = client.get(f"/v1/applications/{application.id}/machines")
    assert machines.status_code == 200
    assert machines.json()["total"] == 1
    assert machines.json()["items"][0]["hostname"] == "CHECKOUT-APP-01"

    sent_tasks = []

    def fake_send_task(task_name: str, *args, **kwargs) -> SimpleNamespace:
        sent_tasks.append(task_name)
        return SimpleNamespace(id="single-application-metrics-sync")

    monkeypatch.setattr("internal.infra.queue.enqueue.celery_app.send_task", fake_send_task)
    sync = client.post(f"/v1/applications/{application.id}/metrics/sync")
    assert sync.status_code == 202
    assert sync.json() == {"task_id": "single-application-metrics-sync"}
    assert sent_tasks == [SYNC_APPLICATION_METRICS_TASK]

    optimizations = client.get(f"/v1/applications/{application.id}/optimizations")
    assert optimizations.status_code == 200
    assert optimizations.json()["total"] == 1
    assert optimizations.json()["items"][0]["id"] == optimization.id

    assert client.get("/v1/applications/9999/machines").status_code == 404
    assert client.post("/v1/applications/9999/metrics/sync").status_code == 404
    assert client.get("/v1/applications/9999/optimizations").status_code == 404


def test_machine_write_endpoints_are_disabled(client: TestClient, db_session: Session) -> None:
    """Machine creation and update should not be publicly exposed."""
    platform = client.post("/v1/platforms", json={"name": "Machine Invariants"}).json()
    machine = _persist_machine(db_session, platform_id=platform["id"], hostname="node-02")

    create_machine = client.post("/v1/machines", json={"platform_id": platform["id"], "hostname": "node-01"})
    assert create_machine.status_code == 405

    update_machine = client.patch(f"/v1/machines/{machine.id}", json={"environment": "prod"})
    assert update_machine.status_code == 405


def test_machine_list_filters_are_paginated(client: TestClient, db_session: Session) -> None:
    """Machine list filters should keep working with the shared paginated envelope."""
    platform = client.post("/v1/platforms", json={"name": "Machine Filter Platform"}).json()
    other_platform = client.post("/v1/platforms", json={"name": "Other Machine Platform"}).json()

    provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "machine filter inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    ).json()
    other_provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": other_platform["id"],
            "name": "other machine inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    ).json()

    db_session.add_all(
        [
            Machine(
                platform_id=platform["id"],
                application="checkout",
                source_provisioner_id=provisioner["id"],
                hostname="checkout-02",
                environment="prod",
                region="eu-west-1",
            ),
            Machine(
                platform_id=platform["id"],
                application="CHECKOUT",
                source_provisioner_id=provisioner["id"],
                hostname="checkout-01",
                environment="prod",
                region="eu-west-1",
            ),
            Machine(
                platform_id=other_platform["id"],
                source_provisioner_id=other_provisioner["id"],
                hostname="checkout-99",
                environment="dev",
                region="us-east-1",
            ),
        ]
    )
    db_session.commit()

    first_page = client.get(
        "/v1/machines",
        params={
            "platform_id": platform["id"],
            "application": "checkout",
            "source_provisioner_id": provisioner["id"],
            "environment": "prod",
            "region": "eu-west-1",
            "offset": 0,
            "limit": 1,
        },
    )
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 2
    assert [item["hostname"] for item in first_page.json()["items"]] == ["CHECKOUT-01"]

    second_page = client.get(
        "/v1/machines",
        params={
            "platform_id": platform["id"],
            "application": "CHECKOUT",
            "source_provisioner_id": provisioner["id"],
            "environment": "prod",
            "region": "eu-west-1",
            "offset": 1,
            "limit": 1,
        },
    )
    assert second_page.status_code == 200
    assert [item["hostname"] for item in second_page.json()["items"]] == ["CHECKOUT-02"]


def test_provisioner_list_filters_are_paginated(client: TestClient) -> None:
    """Provisioner list filters should keep working with the shared paginated envelope."""
    platform = client.post("/v1/platforms", json={"name": "Provisioner Filter Platform"}).json()
    other_platform = client.post("/v1/platforms", json={"name": "Other Provisioner Platform"}).json()

    alpha = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "alpha inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    ).json()
    zeta = client.post(
        "/v1/machines/provisioners/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "zeta inventory",
            "url": "https://dynatrace.example",
            "token": "dynatrace-secret",
            "cron": "* * * * *",
        },
    ).json()
    client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "disabled inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    )
    client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": other_platform["id"],
            "name": "other inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    )
    client.post(f"/v1/machines/provisioners/{alpha['id']}/enable")
    client.post(f"/v1/machines/provisioners/{zeta['id']}/enable")

    first_page = client.get(
        "/v1/machines/provisioners",
        params={"platform_id": platform["id"], "enabled": True, "offset": 0, "limit": 1},
    )
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 2
    assert [item["name"] for item in first_page.json()["items"]] == ["alpha inventory"]

    second_page = client.get(
        "/v1/machines/provisioners",
        params={"platform_id": platform["id"], "enabled": True, "offset": 1, "limit": 1},
    )
    assert second_page.status_code == 200
    assert [item["name"] for item in second_page.json()["items"]] == ["zeta inventory"]

    disabled_page = client.get(
        "/v1/machines/provisioners",
        params={"platform_id": platform["id"], "enabled": False, "offset": 0, "limit": 10},
    )
    assert disabled_page.status_code == 200
    assert disabled_page.json()["total"] == 1
    assert [item["name"] for item in disabled_page.json()["items"]] == ["disabled inventory"]


def test_machine_read_delete_and_flavor_history_endpoint(client: TestClient, db_session: Session) -> None:
    """Machines should expose read, delete, and flavor history routes."""
    platform = client.post("/v1/platforms", json={"name": "Proxmox"}).json()
    machine = _persist_machine(
        db_session,
        platform_id=platform["id"],
        hostname="node-01",
        region="eu",
        environment="dev",
        cpu=2,
        ram_mb=8 * 1024,
        disk_mb=80 * 1024,
    )

    fetched = client.get(f"/v1/machines/{machine.id}")
    assert fetched.status_code == 200
    assert fetched.json()["environment"] == "DEV"

    history = client.get(f"/v1/machines/{machine.id}/flavor-history").json()
    assert history == {"items": [], "offset": 0, "limit": 100, "total": 0}

    deleted = client.delete(f"/v1/machines/{machine.id}")
    assert deleted.status_code == 204
    assert client.get(f"/v1/machines/{machine.id}").status_code == 404

    missing_history = client.get("/v1/machines/9999/flavor-history")
    assert missing_history.status_code == 404
    assert missing_history.json()["detail"] == "machine not found"


def test_machine_flavor_history_returns_changed_state_only(client: TestClient, db_session: Session) -> None:
    """Flavor history should expose only the changed state in CPU and MB units."""
    platform = Platform(name="Flavor History")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        hostname="node-01",
        cpu=2,
        ram_mb=8 * 1024,
        disk_mb=80 * 1024,
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

    history = client.get(f"/v1/machines/{machine.id}/flavor-history")
    assert history.status_code == 200
    assert history.json()["total"] == 1
    assert history.json()["items"][0]["machine_id"] == machine.id
    assert history.json()["items"][0]["source_provisioner_id"] == provisioner.id
    assert history.json()["items"][0]["cpu"] == 4
    assert history.json()["items"][0]["ram_mb"] == 16384
    assert history.json()["items"][0]["disk_mb"] == 122880
    history_item_keys = set(history.json()["items"][0])
    assert history_item_keys == {
        "id",
        "machine_id",
        "source_provisioner_id",
        "cpu",
        "ram_mb",
        "disk_mb",
        "changed_at",
    }


def test_machine_flavor_history_lists_initial_and_changed_inventory_snapshots(
    client: TestClient,
    db_session: Session,
) -> None:
    """Flavor history should expose inventory snapshots from creation to later changes."""
    platform = Platform(name="Inventory Flavor Timeline")
    provisioner = MachineProvisioner(
        platform=platform,
        name="inventory",
        type="mock_inventory",
        enabled=True,
        cron="* * * * *",
        config={
            "machines": [
                {
                    "external_id": "node-01",
                    "hostname": "node-01",
                    "cpu": 2,
                    "ram_mb": 8 * 1024,
                    "disk_mb": 80 * 1024,
                }
            ]
        },
    )
    db_session.add_all([platform, provisioner])
    db_session.commit()

    assert run_provisioner_inventory(db_session, provisioner.id) == {"created": 1, "updated": 0, "flavor_changes": 0}

    provisioner.config = {
        "machines": [
            {
                "external_id": "node-01",
                "hostname": "node-01",
                "cpu": 4,
                "ram_mb": 16 * 1024,
                "disk_mb": 120 * 1024,
            }
        ]
    }
    db_session.commit()

    assert run_provisioner_inventory(db_session, provisioner.id) == {"created": 0, "updated": 1, "flavor_changes": 1}

    machine = db_session.query(Machine).filter(Machine.source_provisioner_id == provisioner.id).one()
    history = client.get(f"/v1/machines/{machine.id}/flavor-history")
    assert history.status_code == 200
    assert history.json()["total"] == 2
    assert history.json()["items"][0]["cpu"] == 4
    assert history.json()["items"][0]["ram_mb"] == 16 * 1024
    assert history.json()["items"][0]["disk_mb"] == 120 * 1024
    assert history.json()["items"][1]["cpu"] == 2
    assert history.json()["items"][1]["ram_mb"] == 8 * 1024
    assert history.json()["items"][1]["disk_mb"] == 80 * 1024


def test_machine_optimization_endpoint_reads_current_projection(client: TestClient, db_session: Session) -> None:
    """Machines should expose the current optimization projection."""
    platform = Platform(name="Optimization API")
    machine = Machine(
        platform=platform,
        hostname="node-02",
        cpu=4,
        ram_mb=8192,
        disk_mb=80 * 1024,
    )
    db_session.add_all([platform, machine])
    db_session.commit()

    db_session.add(
        MachineOptimization(
            machine_id=machine.id,
            status="ready",
            action="scale_up",
            window_size=30,
            min_cpu=1,
            max_cpu=64,
            min_ram_mb=2048,
            max_ram_mb=262144,
            computed_at=machine.updated_at,
            current_cpu=4,
            current_ram_mb=8192,
            current_disk_mb=80 * 1024,
            target_cpu=6,
            target_ram_mb=8192,
            target_disk_mb=80 * 1024,
            details={
                "cpu": {
                    "provider_id": 7,
                    "status": "ok",
                    "samples_used": 1,
                    "last_metric_date": "2026-05-02",
                    "utilization_percent": 92.0,
                    "current_capacity": 4,
                    "raw_target_capacity": 5.6615384615,
                    "bounded_target_capacity": 6,
                    "action": "scale_up",
                    "reason_code": "limited_history",
                }
            },
        )
    )
    db_session.commit()

    current = client.get(f"/v1/machines/{machine.id}/optimizations")
    assert current.status_code == 200
    assert current.json()["resources"]["cpu"] == {
        "status": "ok",
        "action": "scale_up",
        "current": 4.0,
        "recommended": 6.0,
        "unit": "cores",
        "utilization_percent": 92.0,
        "reason": "limited_history",
    }
    assert "revision" not in current.json()
    assert "is_current" not in current.json()
    assert "target_cpu" not in current.json()
    assert "details" not in current.json()


def test_machine_optimization_endpoint_exposes_catalog_bound_reasons(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """Optimization responses should expose min and above-max recommendation reasons."""
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_WINDOW_SIZE", "1")
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_MIN_CPU", "2")
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_MAX_CPU", "4")
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_MIN_RAM_MB", "4096")
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_MAX_RAM_MB", "8192")
    get_settings.cache_clear()

    platform = Platform(name="Optimization Catalog Bounds API")
    provisioner = MachineProvisioner(platform=platform, name="inventory", type="mock_inventory", cron="* * * * *")
    machine = Machine(
        platform=platform,
        source_provisioner=provisioner,
        hostname="node-catalog-bounds",
        cpu=1,
        ram_mb=4096,
        disk_mb=80 * 1024,
    )
    cpu_provider = MachineProvider(
        platform=platform,
        name="cpu",
        type="mock_metric",
        scope="cpu",
        enabled=True,
        provisioners=[provisioner],
    )
    ram_provider = MachineProvider(
        platform=platform,
        name="ram",
        type="mock_metric",
        scope="ram",
        enabled=True,
        provisioners=[provisioner],
    )
    db_session.add_all([machine, cpu_provider, ram_provider])
    db_session.commit()
    db_session.add_all(
        [
            MachineCPUMetric(provider_id=cpu_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=10),
            MachineRAMMetric(provider_id=ram_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=200),
        ]
    )

    refresh_machine_optimization(db_session, machine.id)
    db_session.commit()

    response = client.get(f"/v1/machines/{machine.id}/optimizations")

    assert response.status_code == 200
    assert response.json()["resources"]["cpu"] == {
        "status": "ok",
        "action": "scale_up",
        "current": 1.0,
        "recommended": 2.0,
        "unit": "cores",
        "utilization_percent": 10.0,
        "reason": "raised_to_min_cpu",
    }
    assert response.json()["resources"]["ram"] == {
        "status": "ok",
        "action": "keep",
        "current": 4096.0,
        "recommended": 4096.0,
        "unit": "mb",
        "utilization_percent": 200.0,
        "reason": "above_max_ram",
    }


def test_machine_optimization_collection_filters(
    client: TestClient,
    db_session: Session,
) -> None:
    """Optimizations should be listable across machines."""
    primary_platform = Platform(name="Optimization Collection API")
    other_platform = Platform(name="Optimization Collection Other")
    current_machine = Machine(
        platform=primary_platform,
        hostname="node-opt-01",
        application="cart",
        environment="prod",
        region="eu",
        cpu=4,
        ram_mb=8192,
        disk_mb=80 * 1024,
    )
    other_machine = Machine(
        platform=other_platform,
        hostname="node-opt-02",
        application="billing",
        environment="dev",
        region="us",
        cpu=2,
        ram_mb=4096,
        disk_mb=40 * 1024,
    )
    db_session.add_all([primary_platform, other_platform, current_machine, other_machine])
    db_session.commit()

    base_details = {
        "cpu": {
            "provider_id": None,
            "status": "missing_provider",
            "samples_used": 0,
            "last_metric_date": None,
            "utilization_percent": None,
            "current_capacity": 4,
            "raw_target_capacity": None,
            "bounded_target_capacity": None,
            "action": "unavailable",
            "reason_code": "no_provider",
        }
    }
    current = MachineOptimization(
        machine_id=current_machine.id,
        status="ready",
        action="scale_up",
        window_size=30,
        min_cpu=1,
        max_cpu=64,
        min_ram_mb=2048,
        max_ram_mb=262144,
        computed_at=current_machine.updated_at,
        current_cpu=4,
        current_ram_mb=8192,
        current_disk_mb=80 * 1024,
        target_cpu=6,
        target_ram_mb=8192,
        target_disk_mb=80 * 1024,
        details=base_details,
    )
    other_current = MachineOptimization(
        machine_id=other_machine.id,
        status="partial",
        action="insufficient_data",
        window_size=30,
        min_cpu=1,
        max_cpu=64,
        min_ram_mb=2048,
        max_ram_mb=262144,
        computed_at=other_machine.updated_at,
        current_cpu=2,
        current_ram_mb=4096,
        current_disk_mb=40 * 1024,
        target_cpu=None,
        target_ram_mb=None,
        target_disk_mb=None,
        details=base_details,
    )
    db_session.add_all([current, other_current])
    db_session.commit()

    default_list = client.get("/v1/machines/optimizations")
    assert default_list.status_code == 200
    assert default_list.json()["total"] == 2
    assert {item["id"] for item in default_list.json()["items"]} == {current.id, other_current.id}

    filtered = client.get(
        "/v1/machines/optimizations",
        params={
            "platform_id": primary_platform.id,
            "application": "cart",
            "environment": "prod",
            "region": "eu",
            "status": "ready",
            "action": "scale_up",
        },
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["id"] == current.id

    limited = client.get("/v1/machines/optimizations", params={"limit": 1})
    assert limited.status_code == 200
    assert limited.json()["limit"] == 1
    assert len(limited.json()["items"]) == 1


def test_machine_optimization_endpoints_handle_missing_state_and_enqueue_recalculation(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """Optimization endpoints should report missing state and allow manual recalculation."""
    platform = Platform(name="Optimization Recalculate API")
    machine = Machine(platform=platform, hostname="node-03")
    db_session.add_all([platform, machine])
    db_session.commit()

    missing = client.get(f"/v1/machines/{machine.id}/optimizations")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "optimization not computed yet"

    monkeypatch.setattr(
        "internal.infra.queue.enqueue.celery_app.send_task",
        lambda *_args, **_kwargs: SimpleNamespace(id="manual-optimization-recalc"),
    )
    response = client.post(f"/v1/machines/{machine.id}/optimizations/recalculate")
    assert response.status_code == 202
    assert response.json() == {"task_id": "manual-optimization-recalc"}

    missing_machine = client.post("/v1/machines/9999/optimizations/recalculate")
    assert missing_machine.status_code == 404


def test_provider_provisioner_list_is_paginated_and_missing_provider_returns_404(client: TestClient) -> None:
    """Provider provisioner lists should paginate and still 404 on missing parents."""
    platform = client.post("/v1/platforms", json={"name": "Provider Provisioner Platform"}).json()
    alpha = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "alpha inventory",
            "token": "capsule-secret",
            "cron": "* * * * *",
        },
    ).json()
    beta = client.post(
        "/v1/machines/provisioners/dynatrace",
        json={
            "platform_id": platform["id"],
            "name": "beta inventory",
            "url": "https://dynatrace.example",
            "token": "dynatrace-secret",
            "cron": "* * * * *",
        },
    ).json()
    provider = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "cpu provider",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    ).json()

    assert client.post(f"/v1/machines/providers/{provider['id']}/provisioners/{alpha['id']}").status_code == 200
    assert client.post(f"/v1/machines/providers/{provider['id']}/provisioners/{beta['id']}").status_code == 200

    first_page = client.get(
        f"/v1/machines/providers/{provider['id']}/provisioners",
        params={"offset": 0, "limit": 1},
    )
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 2
    assert [item["name"] for item in first_page.json()["items"]] == ["alpha inventory"]

    second_page = client.get(
        f"/v1/machines/providers/{provider['id']}/provisioners",
        params={"offset": 1, "limit": 1},
    )
    assert second_page.status_code == 200
    assert [item["name"] for item in second_page.json()["items"]] == ["beta inventory"]

    missing_provider = client.get("/v1/machines/providers/9999/provisioners")
    assert missing_provider.status_code == 404
    assert missing_provider.json()["detail"] == "provider not found"


def test_provisioner_sync_and_child_routes(
    client: TestClient,
    db_session: Session,
    monkeypatch,
) -> None:
    """Provisioner child routes should list discovered machines and attached providers."""
    platform = client.post("/v1/platforms", json={"name": "Provisioner Child Platform"}).json()
    provisioner = client.post(
        "/v1/machines/provisioners/capsule",
        json={
            "platform_id": platform["id"],
            "name": "child inventory",
            "token": "capsule-secret",
        },
    ).json()
    provider = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "child cpu",
            "scope": "cpu",
            "url": "https://prometheus.example",
            "query": "avg(up)",
        },
    ).json()
    attach = client.post(f"/v1/machines/providers/{provider['id']}/provisioners/{provisioner['id']}")
    assert attach.status_code == 200
    db_session.add(
        Machine(
            platform_id=platform["id"],
            source_provisioner_id=provisioner["id"],
            hostname="provisioner-child-01",
        )
    )
    db_session.commit()

    machines = client.get(f"/v1/machines/provisioners/{provisioner['id']}/machines")
    assert machines.status_code == 200
    assert machines.json()["total"] == 1
    assert machines.json()["items"][0]["hostname"] == "PROVISIONER-CHILD-01"

    providers = client.get(f"/v1/machines/provisioners/{provisioner['id']}/providers")
    assert providers.status_code == 200
    assert providers.json()["total"] == 1
    assert providers.json()["items"][0]["id"] == provider["id"]
    assert providers.json()["items"][0]["provisioner_ids"] == [provisioner["id"]]

    sent_tasks = []

    def fake_send_task(task_name: str, *args, **kwargs) -> SimpleNamespace:
        sent_tasks.append(task_name)
        return SimpleNamespace(id="manual-provisioner-sync")

    monkeypatch.setattr("internal.infra.queue.enqueue.celery_app.send_task", fake_send_task)
    sync = client.post("/v1/machines/provisioners/sync")
    assert sync.status_code == 202
    assert sync.json() == {"task_id": "manual-provisioner-sync"}
    assert sent_tasks == [DISPATCH_DUE_MACHINE_PROVISIONER_JOBS_TASK]

    assert client.get("/v1/machines/provisioners/9999/machines").status_code == 404
    assert client.get("/v1/machines/provisioners/9999/providers").status_code == 404


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

    missing_type = client.get(f"/v1/machines/{machine.id}/metrics")
    assert missing_type.status_code == 422

    first_page = client.get(
        f"/v1/machines/{machine.id}/metrics",
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
        f"/v1/machines/{machine.id}/metrics",
        params={"type": "cpu", "offset": 1, "limit": 1},
    )
    assert second_page.status_code == 200
    assert second_page.json()["total"] == 2
    assert second_page.json()["items"][0]["date"] == "2026-05-01"
    assert second_page.json()["items"][0]["value"] == 10

    missing_machine = client.get("/v1/machines/9999/metrics", params={"type": "cpu"})
    assert missing_machine.status_code == 404
    assert missing_machine.json()["detail"] == "machine not found"


def test_machine_latest_metrics_returns_each_scope_or_null(client: TestClient, db_session: Session) -> None:
    """Latest metrics should expose one sample per scope and null when missing."""
    platform = Platform(name="Latest Machine Metrics")
    machine = Machine(platform=platform, hostname="latest-node-01")
    cpu_provider = MachineProvider(
        platform=platform,
        name="cpu provider",
        type="prometheus",
        scope="cpu",
        config={"url": "https://prometheus.example", "query": "avg(up)"},
    )
    disk_provider = MachineProvider(
        platform=platform,
        name="disk provider",
        type="prometheus",
        scope="disk",
        config={"url": "https://prometheus.example", "query": "avg(disk)"},
    )
    db_session.add_all([platform, machine, cpu_provider, disk_provider])
    db_session.commit()
    db_session.add_all(
        [
            MachineCPUMetric(provider_id=cpu_provider.id, machine_id=machine.id, date=date(2026, 5, 1), value=10),
            MachineCPUMetric(provider_id=cpu_provider.id, machine_id=machine.id, date=date(2026, 5, 2), value=20),
            MachineDiskMetric(provider_id=disk_provider.id, machine_id=machine.id, date=date(2026, 5, 3), value=70),
        ]
    )
    db_session.commit()

    response = client.get(f"/v1/machines/{machine.id}/metrics/latest")

    assert response.status_code == 200
    assert response.json()["cpu"]["provider_id"] == cpu_provider.id
    assert response.json()["cpu"]["date"] == "2026-05-02"
    assert response.json()["cpu"]["value"] == 20
    assert response.json()["ram"] is None
    assert response.json()["disk"]["provider_id"] == disk_provider.id
    assert response.json()["disk"]["date"] == "2026-05-03"
    assert response.json()["disk"]["value"] == 70

    missing = client.get("/v1/machines/9999/metrics/latest")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "machine not found"


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

    missing_type = client.get("/v1/machines/metrics")
    assert missing_type.status_code == 422

    invalid_type = client.get("/v1/machines/metrics", params={"type": "gpu"})
    assert invalid_type.status_code == 422

    response = client.get(
        "/v1/machines/metrics",
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
        "/v1/machines/metrics",
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
