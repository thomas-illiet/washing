"""Provider metric collection use cases."""

from collections.abc import Callable

from sqlalchemy.orm import Query, Session, selectinload

from internal.domain import normalize_external_id, normalize_hostname
from internal.infra.connectors.base import MetricRecord
from internal.infra.connectors.registry import get_metric_collector
from internal.infra.db.base import utcnow
from internal.infra.db.models import Machine, MachineCPUMetric, MachineDiskMetric, MachineProvider, MachineRAMMetric
from internal.infra.security import sanitize_operational_error


METRIC_MODELS = {
    "cpu": MachineCPUMetric,
    "ram": MachineRAMMetric,
    "disk": MachineDiskMetric,
}


def metric_model_for_code(code: str):
    """Return the SQLAlchemy metric table for a metric type code."""
    try:
        return METRIC_MODELS[code.lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported metric type table for code: {code}") from exc


def _load_provider(db: Session, provider_id: int) -> MachineProvider | None:
    """Load one provider together with its provisioner attachments."""
    return (
        db.query(MachineProvider)
        .options(selectinload(MachineProvider.provisioners))
        .filter(MachineProvider.id == provider_id)
        .one_or_none()
    )


def _scoped_machine_query(db: Session, provider: MachineProvider) -> Query[Machine]:
    """Build the machine query visible to one provider scope."""
    query = db.query(Machine).filter(Machine.platform_id == provider.platform_id)
    provisioner_ids = [provisioner.id for provisioner in provider.provisioners]
    if provisioner_ids:
        query = query.filter(Machine.source_provisioner_id.in_(provisioner_ids))
    return query


def _scoped_machines(db: Session, provider: MachineProvider) -> list[Machine]:
    """Return the machines visible to the provider scope."""
    return _scoped_machine_query(db, provider).order_by(Machine.id.asc()).all()


def _scoped_machine(db: Session, provider: MachineProvider, machine_id: int) -> Machine | None:
    """Return one machine only when it is visible to the provider scope."""
    return _scoped_machine_query(db, provider).filter(Machine.id == machine_id).one_or_none()


def _resolve_machine_id(record: MetricRecord, machines: list[Machine]) -> int | None:
    """Resolve a metric record to a stored machine id."""
    machine_external_id = normalize_external_id(record.machine_external_id)
    hostname = normalize_hostname(record.hostname)
    if record.machine_id is not None:
        return record.machine_id
    if machine_external_id is not None:
        for machine in machines:
            if machine.external_id == machine_external_id:
                return machine.id
    if hostname is not None:
        for machine in machines:
            if machine.hostname == hostname:
                return machine.id
    return None


def _upsert_daily_metric(db: Session, provider: MachineProvider, record: MetricRecord, machines: list[Machine]):
    """Insert or update the daily metric row targeted by one record."""
    metric_code = provider.scope.lower()
    metric_model = metric_model_for_code(metric_code)
    metric_date = record.date or utcnow().date()
    machine_id = _resolve_machine_id(record, machines)
    if machine_id is None:
        return "skipped"

    values = {
        "provider_id": provider.id,
        "machine_id": machine_id,
        "date": metric_date,
        "value": int(record.value),
    }
    query = db.query(metric_model).filter(
        metric_model.provider_id == provider.id,
        metric_model.machine_id == machine_id,
        metric_model.date == metric_date,
    )

    existing = query.one_or_none()
    if existing is None:
        db.add(metric_model(**values))
        return "created"

    for field, value in values.items():
        setattr(existing, field, value)
    return "updated"


def dispatch_enabled_provider_syncs(
    db: Session,
    enqueue_provider: Callable[[int], str],
) -> dict[str, list[int]]:
    """Enqueue one provider dispatcher task per enabled provider."""
    provider_ids = [
        provider_id
        for provider_id, in (
            db.query(MachineProvider.id)
            .filter(MachineProvider.enabled.is_(True))
            .order_by(MachineProvider.id.asc())
            .all()
        )
    ]
    for provider_id in provider_ids:
        enqueue_provider(provider_id)
    return {"providers": provider_ids}


def dispatch_provider_machine_syncs(
    db: Session,
    provider_id: int,
    enqueue_machine_sync: Callable[[int, int], str],
) -> dict[str, int | list[int] | str]:
    """Enqueue one metric collection task per machine visible to a provider."""
    provider = _load_provider(db, provider_id)
    if provider is None:
        return {"provider_id": provider_id, "machines": [], "status": "provider_not_found"}

    now = utcnow()
    provider.last_run_at = now
    provider.last_error = None
    db.commit()
    provider = _load_provider(db, provider_id)
    if provider is None:
        return {"provider_id": provider_id, "machines": [], "status": "provider_not_found"}

    machine_ids = [machine.id for machine in _scoped_machines(db, provider)]
    for machine_id in machine_ids:
        enqueue_machine_sync(provider.id, machine_id)
    return {"provider_id": provider.id, "machines": machine_ids}


def run_provider_machine_collection(db: Session, provider_id: int, machine_id: int) -> dict[str, int | str]:
    """Run one provider collection for a single machine/provider pair."""
    provider = _load_provider(db, provider_id)
    if provider is None:
        return {
            "provider_id": provider_id,
            "machine_id": machine_id,
            "created": 0,
            "updated": 0,
            "skipped": 1,
            "status": "provider_not_found",
        }

    machine = _scoped_machine(db, provider, machine_id)
    if machine is None:
        status = "machine_not_found" if db.get(Machine, machine_id) is None else "machine_out_of_scope"
        return {
            "provider_id": provider.id,
            "machine_id": machine_id,
            "created": 0,
            "updated": 0,
            "skipped": 1,
            "status": status,
        }

    try:
        connector = get_metric_collector(provider.type)
        records = connector.collect(provider, [machine])
        result = "skipped"
        if records:
            # One task is responsible for one provider/machine pair, so we persist
            # at most the first returned daily sample for that pair.
            result = _upsert_daily_metric(db, provider, records[0], [machine])

        provider.last_success_at = utcnow()
        db.commit()
        return {
            "provider_id": provider.id,
            "machine_id": machine.id,
            "created": 1 if result == "created" else 0,
            "updated": 1 if result == "updated" else 0,
            "skipped": 1 if result == "skipped" else 0,
        }
    except Exception as exc:
        db.rollback()
        provider = db.get(MachineProvider, provider_id)
        if provider is not None:
            provider.last_error = sanitize_operational_error(exc)
            db.commit()
        raise
