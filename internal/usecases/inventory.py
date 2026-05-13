"""Inventory synchronization use cases."""

from sqlalchemy.orm import Session

from internal.domain import (
    normalize_application_code,
    normalize_dimension,
    normalize_external_id,
    normalize_hostname,
)
from internal.infra.connectors.base import MachineRecord
from internal.infra.connectors.registry import get_machine_provisioner
from internal.infra.db.base import utcnow
from internal.infra.db.models import Machine, MachineFlavorHistory, MachineProvisioner
from internal.infra.security import sanitize_operational_error
from internal.usecases.optimizations import refresh_machine_optimization

PROVISIONER_DISABLED_DETAIL = "provisioner must be enabled before it can run"


def _find_machine(db: Session, provisioner: MachineProvisioner, record: MachineRecord) -> Machine | None:
    """Find the machine matched by external id first, then by hostname."""
    if record.external_id:
        machine = (
            db.query(Machine)
            .filter(
                Machine.source_provisioner_id == provisioner.id,
                Machine.external_id == record.external_id,
            )
            .one_or_none()
        )
        if machine is not None:
            return machine

    return (
        db.query(Machine)
        .filter(
            Machine.platform_id == provisioner.platform_id,
            Machine.hostname == record.hostname,
        )
        .one_or_none()
    )


def _flavor_changed(machine: Machine, record: MachineRecord) -> bool:
    """Return whether compute resources changed for the incoming record."""
    return (
        machine.cpu != record.cpu
        or machine.ram_mb != record.ram_mb
        or machine.disk_mb != record.disk_mb
    )


def _resolve_application(record: MachineRecord) -> str | None:
    """Resolve the canonical application code linked to a machine record."""
    return normalize_application_code(record.application)


def _normalize_machine_record(record: MachineRecord) -> MachineRecord:
    """Return a record with canonical casing for persisted machine identifiers."""
    return MachineRecord(
        external_id=normalize_external_id(record.external_id),
        hostname=normalize_hostname(record.hostname) or record.hostname,
        application=normalize_application_code(record.application),
        region=normalize_dimension(record.region),
        environment=normalize_dimension(record.environment),
        cpu=record.cpu,
        ram_mb=record.ram_mb,
        disk_mb=record.disk_mb,
        extra=record.extra,
    )


def _record_flavor_snapshot(
    db: Session,
    machine: Machine,
    provisioner: MachineProvisioner,
    record: MachineRecord,
    changed_at,
) -> None:
    """Persist one observed machine flavor snapshot."""
    db.add(
        MachineFlavorHistory(
            machine=machine,
            source_provisioner_id=provisioner.id,
            cpu=record.cpu,
            ram_mb=record.ram_mb,
            disk_mb=record.disk_mb,
            changed_at=changed_at,
        )
    )


def run_provisioner_inventory(db: Session, provisioner_id: int) -> dict[str, int]:
    """Run one provisioner discovery and upsert the resulting machine inventory."""
    provisioner = db.get(MachineProvisioner, provisioner_id)
    if provisioner is None:
        raise ValueError(f"provisioner {provisioner_id} not found")

    now = utcnow()
    provisioner.last_run_at = now
    provisioner.last_error = None
    db.commit()
    db.refresh(provisioner)

    if not provisioner.enabled:
        provisioner.last_error = sanitize_operational_error(PROVISIONER_DISABLED_DETAIL)
        db.commit()
        raise ValueError(PROVISIONER_DISABLED_DETAIL)

    try:
        connector = get_machine_provisioner(provisioner.type)
        records = connector.discover(provisioner)
        created = 0
        updated = 0
        flavor_changes = 0
        optimization_machine_ids: set[int] = set()

        for record in records:
            record = _normalize_machine_record(record)
            machine = _find_machine(db, provisioner, record)
            application = _resolve_application(record)
            if machine is None:
                machine = Machine(
                    platform_id=provisioner.platform_id,
                    application=application,
                    source_provisioner_id=provisioner.id,
                    external_id=record.external_id,
                    hostname=record.hostname,
                    region=record.region,
                    environment=record.environment,
                    cpu=record.cpu,
                    ram_mb=record.ram_mb,
                    disk_mb=record.disk_mb,
                    extra=record.extra,
                )
                db.add(machine)
                db.flush()
                _record_flavor_snapshot(db, machine, provisioner, record, now)
                optimization_machine_ids.add(machine.id)
                created += 1
                continue

            if _flavor_changed(machine, record):
                _record_flavor_snapshot(db, machine, provisioner, record, now)
                flavor_changes += 1
                optimization_machine_ids.add(machine.id)

            machine.source_provisioner_id = provisioner.id
            machine.application = application
            machine.external_id = record.external_id
            machine.hostname = record.hostname
            machine.region = record.region
            machine.environment = record.environment
            machine.cpu = record.cpu
            machine.ram_mb = record.ram_mb
            machine.disk_mb = record.disk_mb
            machine.extra = record.extra
            updated += 1

        for optimization_machine_id in sorted(optimization_machine_ids):
            refresh_machine_optimization(db, optimization_machine_id)

        provisioner.last_success_at = now
        provisioner.last_error = None
        db.commit()
        return {"created": created, "updated": updated, "flavor_changes": flavor_changes}
    except Exception as exc:
        db.rollback()
        provisioner = db.get(MachineProvisioner, provisioner_id)
        if provisioner is not None:
            provisioner.last_error = sanitize_operational_error(exc)
            db.commit()
        raise
