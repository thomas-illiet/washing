"""End-to-end coverage for the machine optimization feature."""

import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.api.main import create_app
from internal.infra.config.settings import get_settings
from internal.infra.db.models import (
    Machine,
    MachineCPUMetric,
    MachineDiskMetric,
    MachineOptimization,
    MachineProvider,
    MachineProvisioner,
    MachineRAMMetric,
)
from internal.usecases.inventory import run_provisioner_inventory
from internal.usecases.metrics import run_provider_machine_collection
from internal.usecases.optimizations import refresh_machine_optimization
from tests.constants import TEST_ENCRYPTION_KEY


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _migrate_sqlite_database(database_path: Path) -> None:
    """Create a fully migrated SQLite database through Alembic."""
    env = os.environ.copy()
    env["APP_NAME"] = "Metrics Collector E2E"
    env["APP_ENV"] = "prod"
    env["OIDC_ENABLED"] = "false"
    env["DATABASE_ENCRYPTION_KEY"] = TEST_ENCRYPTION_KEY
    env["DATABASE_URL"] = f"sqlite:///{database_path}"

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def _session_for_migrated_sqlite_database(database_path: Path) -> tuple[Session, object]:
    """Open a SQLAlchemy session against an Alembic-created SQLite database."""
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return session_factory(), engine


def _append_metric_window(db: Session, provider_id: int, machine_id: int, metric_model, values: list[int]) -> None:
    """Add older metric rows so the optimization has a full averaging window."""
    latest_date = (
        db.query(metric_model.date)
        .filter(metric_model.provider_id == provider_id)
        .filter(metric_model.machine_id == machine_id)
        .order_by(metric_model.date.desc())
        .limit(1)
        .scalar()
    )
    assert latest_date is not None

    for offset, value in enumerate(values, start=1):
        db.add(
            metric_model(
                provider_id=provider_id,
                machine_id=machine_id,
                date=latest_date - timedelta(days=offset),
                value=value,
            )
        )
    db.commit()


def test_machine_optimization_full_e2e_on_migrated_database(tmp_path: Path, monkeypatch) -> None:
    """Exercise optimization from migrated schema through workers and public API."""
    database_path = tmp_path / "optimizations-e2e.db"
    monkeypatch.setenv("APP_NAME", "Metrics Collector E2E")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("OIDC_ENABLED", "false")
    monkeypatch.setenv("DATABASE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("FLAVOR_OPTIMIZATION_WINDOW_SIZE", "3")
    get_settings.cache_clear()

    _migrate_sqlite_database(database_path)
    db, engine = _session_for_migrated_sqlite_database(database_path)
    app = create_app(validate_database_on_startup=True)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            platform_response = client.post("/v1/platforms", json={"name": "Optimization E2E"})
            assert platform_response.status_code == 201
            platform_id = platform_response.json()["id"]

            provisioner = MachineProvisioner(
                platform_id=platform_id,
                name="inventory",
                type="mock_inventory",
                enabled=True,
                cron="* * * * *",
                config={
                    "machines": [
                        {
                            "external_id": "vm-e2e",
                            "hostname": "vm-e2e",
                            "application": "checkout",
                            "environment": "prod",
                            "region": "eu",
                            "cpu": 2,
                            "ram_mb": 8192,
                            "disk_mb": 80 * 1024,
                        }
                    ]
                },
            )
            cpu_provider = MachineProvider(
                platform_id=platform_id,
                name="cpu-p95",
                type="mock_metric",
                scope="cpu",
                enabled=True,
                config={"value": 90},
                provisioners=[provisioner],
            )
            ram_provider = MachineProvider(
                platform_id=platform_id,
                name="ram-p95",
                type="mock_metric",
                scope="ram",
                enabled=True,
                config={"value": 35},
                provisioners=[provisioner],
            )
            disk_provider = MachineProvider(
                platform_id=platform_id,
                name="disk-used",
                type="mock_metric",
                scope="disk",
                enabled=True,
                config={"value": 90},
                provisioners=[provisioner],
            )
            db.add_all([provisioner, cpu_provider, ram_provider, disk_provider])
            db.commit()

            assert run_provisioner_inventory(db, provisioner.id) == {
                "created": 1,
                "updated": 0,
                "flavor_changes": 0,
            }
            machine = db.query(Machine).filter(Machine.external_id == "vm-e2e").one()

            initial_response = client.get(f"/v1/machines/{machine.id}/optimizations")
            assert initial_response.status_code == 200
            assert initial_response.json()["status"] == "partial"
            assert initial_response.json()["resources"]["cpu"]["reason"] == "no_samples"
            assert initial_response.json()["resources"]["cpu"]["recommended"] is None

            assert run_provider_machine_collection(db, cpu_provider.id, machine.id)["created"] == 1
            assert run_provider_machine_collection(db, ram_provider.id, machine.id)["created"] == 1
            assert run_provider_machine_collection(db, disk_provider.id, machine.id)["created"] == 1

            limited_history_response = client.get(f"/v1/machines/{machine.id}/optimizations")
            assert limited_history_response.status_code == 200
            limited_history = limited_history_response.json()
            assert limited_history["status"] == "ready"
            assert limited_history["action"] == "mixed"
            assert set(limited_history["resources"]) == {"cpu", "ram", "disk"}
            assert "details" not in limited_history
            assert "window_size" not in limited_history
            assert "target_cpu" not in limited_history
            assert limited_history["resources"]["cpu"] == {
                "status": "ok",
                "action": "scale_up",
                "current": 2.0,
                "recommended": 3.0,
                "unit": "cores",
                "utilization_percent": 90.0,
                "reason": "limited_history",
            }
            assert limited_history["resources"]["ram"]["recommended"] == 5120.0
            assert limited_history["resources"]["ram"]["recommended"] % 1024 == 0
            assert limited_history["resources"]["ram"]["action"] == "scale_down"
            assert limited_history["resources"]["ram"]["reason"] == "limited_history"
            assert limited_history["resources"]["disk"]["recommended"] == 113664.0
            assert limited_history["resources"]["disk"]["recommended"] % 1024 == 0
            assert limited_history["resources"]["disk"]["action"] == "scale_up"

            cpu_metrics = client.get(f"/v1/machines/{machine.id}/metrics", params={"type": "cpu"})
            assert cpu_metrics.status_code == 200
            assert cpu_metrics.json()["total"] == 1

            _append_metric_window(db, cpu_provider.id, machine.id, MachineCPUMetric, [80, 100])
            _append_metric_window(db, ram_provider.id, machine.id, MachineRAMMetric, [30, 40])
            _append_metric_window(db, disk_provider.id, machine.id, MachineDiskMetric, [90, 90])
            refresh_machine_optimization(db, machine.id)
            db.commit()

            full_window_response = client.get(f"/v1/machines/{machine.id}/optimizations")
            assert full_window_response.status_code == 200
            full_window = full_window_response.json()
            assert full_window["status"] == "ready"
            assert full_window["action"] == "mixed"
            assert full_window["revision"] > limited_history["revision"]
            assert full_window["resources"]["cpu"]["utilization_percent"] == 90.0
            assert full_window["resources"]["cpu"]["reason"] == "pressure_high"
            assert full_window["resources"]["ram"]["utilization_percent"] == 35.0
            assert full_window["resources"]["ram"]["reason"] == "pressure_low"
            assert full_window["resources"]["disk"]["utilization_percent"] == 90.0
            assert full_window["resources"]["disk"]["reason"] == "pressure_high"

            filtered_list = client.get(
                "/v1/machines/optimizations",
                params={"platform_id": platform_id, "status": "ready", "action": "mixed"},
            )
            assert filtered_list.status_code == 200
            assert filtered_list.json()["total"] == 1
            assert filtered_list.json()["items"][0]["id"] == full_window["id"]

            history = client.get(
                f"/v1/machines/{machine.id}/optimizations/history",
                params={"limit": 10},
            )
            assert history.status_code == 200
            assert history.json()["total"] == 5
            assert history.json()["items"][0]["id"] == full_window["id"]
            assert history.json()["items"][0]["is_current"] is True
            assert all(item["id"] != full_window["id"] or item["is_current"] for item in history.json()["items"])

            acknowledged = client.post(f"/v1/machines/optimizations/{full_window['id']}/acknowledge")
            assert acknowledged.status_code == 200
            assert acknowledged.json()["acknowledged_at"] is not None
            assert acknowledged.json()["resources"]["disk"]["recommended"] == 113664.0

            acknowledged_list = client.get("/v1/machines/optimizations", params={"acknowledged": True})
            assert acknowledged_list.status_code == 200
            assert acknowledged_list.json()["total"] == 1
            assert acknowledged_list.json()["items"][0]["id"] == full_window["id"]

            current_rows = (
                db.query(MachineOptimization)
                .filter(MachineOptimization.machine_id == machine.id)
                .filter(MachineOptimization.is_current.is_(True))
                .all()
            )
            assert len(current_rows) == 1
    finally:
        app.dependency_overrides.clear()
        db.close()
        engine.dispose()
        get_settings.cache_clear()
