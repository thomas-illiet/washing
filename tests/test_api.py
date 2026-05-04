from fastapi.testclient import TestClient


def test_crud_and_provider_provisioner_association(client: TestClient) -> None:
    platform = client.post("/platforms", json={"name": "VMWare"}).json()

    provisioner = client.post(
        "/provisioners",
        json={
            "platform_id": platform["id"],
            "name": "mock inventory",
            "type": "mock_inventory",
            "cron": "* * * * *",
        },
    ).json()

    provider = client.post(
        "/providers",
        json={
            "platform_id": platform["id"],
            "metric_type_id": 1,
            "name": "mock cpu",
            "type": "mock_metric",
            "cron": "* * * * *",
            "provisioner_ids": [provisioner["id"]],
        },
    ).json()

    assert provider["provisioner_ids"] == [provisioner["id"]]

    associated = client.get(f"/providers/{provider['id']}/provisioners").json()
    assert associated[0]["id"] == provisioner["id"]

    response = client.delete(f"/providers/{provider['id']}/provisioners/{provisioner['id']}")
    assert response.status_code == 204

    provider = client.get(f"/providers/{provider['id']}").json()
    assert provider["provisioner_ids"] == []


def test_application_crud_and_machine_application_id(client: TestClient) -> None:
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
