"""Inventory synchronization use cases."""

from sqlalchemy.orm import Session

from internal.infra.connectors.base import MachineRecord
from internal.infra.connectors.registry import get_machine_provisioner
from internal.infra.db.base import utcnow
from internal.infra.db.models import Application, Machine, MachineFlavorHistory, MachineProvisioner


def _gb_to_mb(value: float | None) -> float | None:
    """Convert GB-style machine capacity values to MB for flavor history."""
    if value is None:
        return None
    return value * 1024


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
        or machine.ram_gb != record.ram_gb
        or machine.disk_gb != record.disk_gb
    )


def _resolve_application_id(db: Session, record: MachineRecord) -> int | None:
    """Resolve or lazily create the application linked to a machine record."""
    if record.application_id is not None:
        return record.application_id
    if record.application_name is None:
        return None

    application = (
        db.query(Application)
        .filter(
            Application.name == record.application_name,
            Application.environment == (record.environment or "unknown"),
            Application.region == (record.region or "unknown"),
        )
        .one_or_none()
    )
    if application is None:
        application = Application(
            name=record.application_name,
            environment=record.environment or "unknown",
            region=record.region or "unknown",
        )
        db.add(application)
        db.flush()
    return application.id


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

    try:
        connector = get_machine_provisioner(provisioner.type)
        records = connector.discover(provisioner)
        created = 0
        updated = 0
        flavor_changes = 0

        for record in records:
            machine = _find_machine(db, provisioner, record)
            application_id = _resolve_application_id(db, record)
            if machine is None:
                machine = Machine(
                    platform_id=provisioner.platform_id,
                    application_id=application_id,
                    source_provisioner_id=provisioner.id,
                    external_id=record.external_id,
                    hostname=record.hostname,
                    region=record.region,
                    environment=record.environment,
                    cpu=record.cpu,
                    ram_gb=record.ram_gb,
                    disk_gb=record.disk_gb,
                    extra=record.extra,
                )
                db.add(machine)
                created += 1
                continue

            if _flavor_changed(machine, record):
                db.add(
                    MachineFlavorHistory(
                        machine=machine,
                        source_provisioner_id=provisioner.id,
                        cpu=record.cpu,
                        ram_mb=_gb_to_mb(record.ram_gb),
                        disk_mb=_gb_to_mb(record.disk_gb),
                        changed_at=now,
                    )
                )
                flavor_changes += 1

            machine.source_provisioner_id = provisioner.id
            machine.application_id = application_id
            machine.external_id = record.external_id
            machine.hostname = record.hostname
            machine.region = record.region
            machine.environment = record.environment
            machine.cpu = record.cpu
            machine.ram_gb = record.ram_gb
            machine.disk_gb = record.disk_gb
            machine.extra = record.extra
            updated += 1

        provisioner.last_success_at = now
        provisioner.last_error = None
        db.commit()
        return {"created": created, "updated": updated, "flavor_changes": flavor_changes}
    except Exception as exc:
        db.rollback()
        provisioner = db.get(MachineProvisioner, provisioner_id)
        if provisioner is not None:
            provisioner.last_error = str(exc)
            db.commit()
        raise
