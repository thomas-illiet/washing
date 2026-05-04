from sqlalchemy.orm import Session, joinedload, selectinload

from internal.infra.connectors.base import MetricRecord
from internal.infra.connectors.registry import get_metric_collector
from internal.infra.db.base import utcnow
from internal.infra.db.models import Machine, MachineCPUMetric, MachineDiskMetric, MachineProvider, MachineRAMMetric


METRIC_MODELS = {
    "cpu": MachineCPUMetric,
    "ram": MachineRAMMetric,
    "disk": MachineDiskMetric,
}


def metric_model_for_code(code: str):
    try:
        return METRIC_MODELS[code.lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported metric type table for code: {code}") from exc


def _scoped_machines(db: Session, provider: MachineProvider) -> list[Machine]:
    query = db.query(Machine).filter(Machine.platform_id == provider.platform_id)
    provisioner_ids = [provisioner.id for provisioner in provider.provisioners]
    if provisioner_ids:
        query = query.filter(Machine.source_provisioner_id.in_(provisioner_ids))
    return query.all()


def _resolve_machine_id(record: MetricRecord, machines: list[Machine]) -> int | None:
    if record.machine_id is not None:
        return record.machine_id
    if record.machine_external_id is not None:
        for machine in machines:
            if machine.external_id == record.machine_external_id:
                return machine.id
    if record.hostname is not None:
        for machine in machines:
            if machine.hostname == record.hostname:
                return machine.id
    return None


def _upsert_daily_metric(db: Session, provider: MachineProvider, record: MetricRecord, machines: list[Machine]):
    metric_code = provider.metric_type.code.lower()
    metric_model = metric_model_for_code(metric_code)
    collected_at = record.collected_at or utcnow()
    machine_id = _resolve_machine_id(record, machines)
    if machine_id is None:
        return "skipped"

    values = {
        "provider_id": provider.id,
        "machine_id": machine_id,
        "metric_date": collected_at.date(),
        "value": record.value,
        "unit": record.unit,
        "labels": record.labels,
        "collected_at": collected_at,
    }
    query = db.query(metric_model).filter(
        metric_model.provider_id == provider.id,
        metric_model.machine_id == machine_id,
        metric_model.metric_date == collected_at.date(),
    )

    if metric_code in {"cpu", "ram"}:
        percentile = float(record.percentile if record.percentile is not None else provider.config.get("percentile", 95.0))
        values["percentile"] = percentile
        query = query.filter(metric_model.percentile == percentile)
    elif metric_code == "disk":
        usage_type = record.usage_type or provider.config.get("usage_type", "used")
        values["usage_type"] = usage_type
        query = query.filter(metric_model.usage_type == usage_type)

    existing = query.one_or_none()
    if existing is None:
        db.add(metric_model(**values))
        return "created"

    for field, value in values.items():
        setattr(existing, field, value)
    return "updated"


def run_provider_collection(db: Session, provider_id: int) -> dict[str, int]:
    provider = (
        db.query(MachineProvider)
        .options(joinedload(MachineProvider.metric_type), selectinload(MachineProvider.provisioners))
        .filter(MachineProvider.id == provider_id)
        .one_or_none()
    )
    if provider is None:
        raise ValueError(f"provider {provider_id} not found")

    now = utcnow()
    provider.last_run_at = now
    provider.last_error = None
    db.commit()
    provider = (
        db.query(MachineProvider)
        .options(joinedload(MachineProvider.metric_type), selectinload(MachineProvider.provisioners))
        .filter(MachineProvider.id == provider_id)
        .one()
    )

    try:
        machines = _scoped_machines(db, provider)
        connector = get_metric_collector(provider.type)
        records = connector.collect(provider, machines)
        created = 0
        updated = 0
        skipped = 0

        for record in records:
            result = _upsert_daily_metric(db, provider, record, machines)
            if result == "created":
                created += 1
            elif result == "updated":
                updated += 1
            else:
                skipped += 1

        provider.last_success_at = now
        provider.last_error = None
        db.commit()
        return {"created": created, "updated": updated, "skipped": skipped}
    except Exception as exc:
        db.rollback()
        provider = db.get(MachineProvider, provider_id)
        if provider is not None:
            provider.last_error = str(exc)
            db.commit()
        raise
