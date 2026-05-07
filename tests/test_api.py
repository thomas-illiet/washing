"""End-to-end API tests for the FastAPI surface."""

from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from internal.domain.cron import INVALID_CRON_EXPRESSION_DETAIL
from internal.infra.config.settings import get_settings
from internal.infra.db.models import (
    Application,
    Machine,
    MachineCPUMetric,
    MachineDiskMetric,
    MachineFlavorHistory,
    MachineProvider,
    MachineProvisioner,
    Platform,
)
from internal.usecases.inventory import run_provisioner_inventory
from internal.usecases.applications import rebuild_applications_from_machines

EXPECTED_OPENAPI_DESCRIPTION = (
    "Inventory and machine metrics API for platforms, applications, providers, and provisioners.\n\n"
    "Use this documentation to browse collection endpoints, operational actions, and async worker tasks."
)

EXPECTED_OPENAPI_TAG_DESCRIPTIONS = {
    "Platforms": "Cycle programs and settings.",
    "Applications": "Loads to track in the drum.",
    "Machines": "Main drum and inventory.",
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
    scheme_container_rule = response.text.split(".swagger-ui .scheme-container {", maxsplit=1)[1].split("}", maxsplit=1)[0]
    assert "backdrop-filter" not in scheme_container_rule


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
    assert "ApplicationCreate" not in schemas
    assert "ApplicationUpdate" not in schemas
    assert {"sync_at", "sync_scheduled_at", "sync_error"} <= set(schemas["ApplicationRead"]["properties"])
    assert "extra" not in schemas["ApplicationRead"]["properties"]
    assert "application" in schemas["MachineRead"]["properties"]
    assert "application_id" not in schemas["MachineRead"]["properties"]
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
    assert "/v1/machines/metrics" in paths
    assert "/v1/machines/{machine_id}/metrics" in paths
    assert "/v1/machines/{machine_id}" in paths
    assert "/v1/machines/providers" in paths
    assert "/v1/machines/providers/{provider_id}" in paths
    assert "/v1/machines/providers/sync" in paths
    assert "/v1/machines/providers/{provider_id}/enable" in paths
    assert "/v1/machines/providers/{provider_id}/disable" in paths
    assert "/v1/machines/providers/{provider_id}/provisioners" in paths
    assert "/v1/machines/providers/mock" not in paths
    assert "/v1/machines/providers/{provider_id}/mock" not in paths
    assert "/v1/machines/provisioners" in paths
    assert "/v1/machines/provisioners/{provisioner_id}" in paths
    assert "/v1/machines/provisioners/mock" not in paths
    assert "/v1/machines/provisioners/{provisioner_id}/mock" not in paths
    assert "/v1/machines/provisioners/{provisioner_id}/enable" in paths
    assert "/v1/machines/provisioners/{provisioner_id}/disable" in paths
    assert "/v1/machines/provisioners/{provisioner_id}/run" in paths
    assert "/v1/applications/sync" in paths
    assert "/v1/worker/tasks" in paths
    assert "Health" not in tags
    assert tags == list(EXPECTED_OPENAPI_TAG_DESCRIPTIONS)
    assert tag_descriptions == EXPECTED_OPENAPI_TAG_DESCRIPTIONS
    assert tags.index("Machines") < tags.index("Machine Metrics")
    assert tags.index("Machine Metrics") < tags.index("Machine Providers")
    assert tags.index("Machine Providers") < tags.index("Machine Provisioners")
    assert paths["/v1/machines"]["get"]["tags"] == ["Machines"]
    assert "post" not in paths["/v1/machines"]
    assert paths["/v1/machines/{machine_id}"]["get"]["tags"] == ["Machines"]
    assert paths["/v1/machines/{machine_id}"]["delete"]["tags"] == ["Machines"]
    assert "patch" not in paths["/v1/machines/{machine_id}"]
    assert paths["/v1/machines/{machine_id}/flavor-history"]["get"]["tags"] == ["Machines"]
    assert paths["/v1/machines/metrics"]["get"]["tags"] == ["Machine Metrics"]
    assert paths["/v1/machines/{machine_id}/metrics"]["get"]["tags"] == ["Machine Metrics"]
    assert paths["/v1/machines/providers"]["get"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/providers/sync"]["post"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/providers/{provider_id}/enable"]["post"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/providers/{provider_id}/prometheus"]["get"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/providers/{provider_id}/provisioners"]["get"]["tags"] == ["Machine Providers"]
    assert paths["/v1/machines/provisioners"]["get"]["tags"] == ["Machine Provisioners"]
    assert paths["/v1/machines/provisioners/{provisioner_id}/enable"]["post"]["tags"] == ["Machine Provisioners"]
    assert paths["/v1/machines/provisioners/{provisioner_id}/dynatrace"]["get"]["tags"] == ["Machine Provisioners"]
    assert paths["/v1/machines/provisioners/{provisioner_id}/run"]["post"]["tags"] == ["Machine Provisioners"]
    assert paths["/v1/applications/sync"]["post"]["tags"] == ["Applications"]
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
        "/v1/machines/metrics",
        "/v1/machines/{machine_id}/metrics",
        "/v1/machines/providers",
        "/v1/machines/providers/{provider_id}/provisioners",
        "/v1/machines/provisioners",
        "/v1/worker/tasks",
    ]:
        _assert_paginated_list_route(body, path)
    assert {"type", "offset", "limit"} <= {param["name"] for param in paths["/v1/machines/metrics"]["get"]["parameters"]}
    assert {"type", "offset", "limit"} <= {
        param["name"] for param in paths["/v1/machines/{machine_id}/metrics"]["get"]["parameters"]
    }


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
            "provisioner_ids": [provisioner["id"]],
        },
    ).json()
    assert prometheus["type"] == "prometheus"
    assert prometheus["enabled"] is False
    assert prometheus["scope"] == "cpu"
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
    assert disabled_run.status_code == 404


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
            "provisioner_ids": [provisioner["id"]],
        },
    )
    assert first_provider.status_code == 201

    second_scope = client.post(
        "/v1/machines/providers/prometheus",
        json={
            "platform_id": platform["id"],
            "name": "prom ram",
            "scope": "ram",
            "url": "https://prometheus.example",
            "query": "avg(node_memory_MemAvailable_bytes)",
            "provisioner_ids": [provisioner["id"]],
        },
    )
    assert second_scope.status_code == 201

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
            "provisioner_ids": [provisioner["id"]],
        },
    ).json()
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
