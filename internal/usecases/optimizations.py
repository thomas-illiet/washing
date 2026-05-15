"""Machine optimization calculation use cases."""

from __future__ import annotations

from math import ceil
from typing import Literal

from sqlalchemy.orm import Session, selectinload

from internal.infra.config.settings import get_settings
from internal.infra.db.base import utcnow
from internal.infra.db.models import (
    Machine,
    MachineCPUMetric,
    MachineDiskMetric,
    MachineProvider,
    MachineRAMMetric,
    MachineOptimization,
)

OptimizationStatus = Literal["ready", "partial", "error"]
OptimizationAction = Literal["scale_up", "scale_down", "mixed", "keep", "insufficient_data", "unavailable"]
ScopeStatus = Literal["ok", "missing_provider", "ambiguous_provider", "insufficient_data", "missing_current_capacity"]
ScopeAction = Literal["scale_up", "scale_down", "keep", "insufficient_data", "unavailable"]
ScopeName = Literal["cpu", "ram", "disk"]

METRIC_MODELS = {
    "cpu": MachineCPUMetric,
    "ram": MachineRAMMetric,
    "disk": MachineDiskMetric,
}

TARGET_UTILIZATION_PERCENT = 65
UPSCALE_UTILIZATION_THRESHOLD = 85
DOWNSCALE_UTILIZATION_THRESHOLD = 40
UPSCALE_CAPACITY_MARGIN = 1.10
DOWNSCALE_CAPACITY_MARGIN = 0.80
CAPACITY_STEP_MB = 1024


def refresh_machine_optimization(db: Session, machine_id: int) -> dict[str, int | str]:
    """Recompute the stored optimization for one machine."""
    machine = db.get(Machine, machine_id)
    if machine is None:
        raise ValueError(f"machine {machine_id} not found")

    db.flush()
    now = utcnow()
    snapshot = _build_optimization_snapshot(db, machine, now)
    current = _current_optimization_query(db, machine_id).one_or_none()

    if current is None:
        db.add(
            MachineOptimization(
                machine_id=machine.id,
                **snapshot,
            )
        )
        return {"machine_id": machine.id, "created": 1, "updated": 0, "status": "created"}

    if _optimization_snapshot_matches(current, snapshot):
        current.computed_at = now
        return {"machine_id": machine.id, "created": 0, "updated": 1, "status": "updated"}

    for field, value in snapshot.items():
        setattr(current, field, value)
    return {"machine_id": machine.id, "created": 0, "updated": 1, "status": "updated"}


def _build_optimization_snapshot(db: Session, machine: Machine, now) -> dict[str, object]:
    """Build the stored snapshot payload for one machine."""
    settings = get_settings()
    scopes = {
        "cpu": _evaluate_scope(
            db,
            machine,
            "cpu",
            machine.cpu,
            settings.flavor_optimization_window_size,
            settings.flavor_optimization_min_cpu,
            settings.flavor_optimization_max_cpu,
        ),
        "ram": _evaluate_scope(
            db,
            machine,
            "ram",
            machine.ram_mb,
            settings.flavor_optimization_window_size,
            settings.flavor_optimization_min_ram_mb,
            settings.flavor_optimization_max_ram_mb,
        ),
        "disk": _evaluate_scope(
            db,
            machine,
            "disk",
            machine.disk_mb,
            settings.flavor_optimization_window_size,
            None,
            None,
        ),
    }
    status, action = _aggregate_optimization(scopes)

    return {
        "status": status,
        "action": action,
        "window_size": settings.flavor_optimization_window_size,
        "min_cpu": settings.flavor_optimization_min_cpu,
        "max_cpu": settings.flavor_optimization_max_cpu,
        "min_ram_mb": settings.flavor_optimization_min_ram_mb,
        "max_ram_mb": settings.flavor_optimization_max_ram_mb,
        "computed_at": now,
        "current_cpu": machine.cpu,
        "current_ram_mb": machine.ram_mb,
        "current_disk_mb": machine.disk_mb,
        "target_cpu": _effective_target(machine.cpu, scopes["cpu"]),
        "target_ram_mb": _effective_target(machine.ram_mb, scopes["ram"]),
        "target_disk_mb": _effective_target(machine.disk_mb, scopes["disk"]),
        "details": scopes,
    }


def _evaluate_scope(
    db: Session,
    machine: Machine,
    scope: ScopeName,
    current_capacity: float | None,
    window_size: int,
    min_capacity: int | None,
    max_capacity: int | None,
) -> dict[str, object]:
    """Evaluate one scope optimization from the latest stored metrics."""
    providers = _visible_enabled_providers_for_scope(db, machine, scope)
    provider_id = providers[0].id if len(providers) == 1 else None
    details = {
        "provider_id": provider_id,
        "status": "ok",
        "samples_used": 0,
        "window_size": window_size,
        "last_metric_date": None,
        "utilization_percent": None,
        "current_capacity": current_capacity,
        "raw_target_capacity": None,
        "bounded_target_capacity": None,
        "action": "keep",
        "reason_code": "within_hysteresis",
    }

    if not providers:
        details["status"] = "missing_provider"
        details["action"] = "unavailable"
        details["reason_code"] = "no_provider"
        return details

    if len(providers) > 1:
        details["status"] = "ambiguous_provider"
        details["action"] = "unavailable"
        details["reason_code"] = "ambiguous_provider"
        return details

    if current_capacity is None:
        details["status"] = "missing_current_capacity"
        details["action"] = "unavailable"
        details["reason_code"] = "missing_current_capacity"
        return details

    samples = _load_metric_samples(db, scope, provider_id=providers[0].id, machine_id=machine.id, limit=window_size)
    details["samples_used"] = len(samples)
    if samples:
        details["last_metric_date"] = samples[0].date.isoformat()

    if not samples:
        details["status"] = "insufficient_data"
        details["action"] = "insufficient_data"
        details["reason_code"] = "no_samples"
        return details

    utilization_percent = _average_metric_value([float(sample.value) for sample in samples])
    raw_target = float(current_capacity) * utilization_percent / TARGET_UTILIZATION_PERCENT
    bounded_target, bound_reason = _bounded_target(scope, raw_target, min_capacity, max_capacity)
    has_limited_history = len(samples) < window_size
    default_reason = "limited_history" if has_limited_history else "within_hysteresis"
    pressure_high_reason = "limited_history" if has_limited_history else "pressure_high"
    pressure_low_reason = "limited_history" if has_limited_history else "pressure_low"
    details["utilization_percent"] = utilization_percent
    details["raw_target_capacity"] = raw_target

    if scope == "cpu" and min_capacity is not None and current_capacity < min_capacity:
        details["bounded_target_capacity"] = float(min_capacity)
        details["action"] = "scale_up"
        details["reason_code"] = "raised_to_min_cpu"
        return details

    if scope == "ram" and min_capacity is not None and current_capacity < min_capacity:
        details["bounded_target_capacity"] = float(min_capacity)
        details["action"] = "scale_up"
        details["reason_code"] = "raised_to_min_ram"
        return details

    details["bounded_target_capacity"] = bounded_target
    pressure_high = utilization_percent >= UPSCALE_UTILIZATION_THRESHOLD
    pressure_low = scope in {"cpu", "ram"} and utilization_percent <= DOWNSCALE_UTILIZATION_THRESHOLD

    if pressure_high and bounded_target is not None:
        if bounded_target > float(current_capacity) * UPSCALE_CAPACITY_MARGIN and bounded_target > float(current_capacity):
            details["action"] = "scale_up"
            details["reason_code"] = bound_reason or pressure_high_reason
            return details

    if pressure_low and bounded_target is not None:
        if bounded_target < float(current_capacity) * DOWNSCALE_CAPACITY_MARGIN and bounded_target < float(current_capacity):
            details["action"] = "scale_down"
            details["reason_code"] = bound_reason or pressure_low_reason
            return details

    details["reason_code"] = bound_reason or default_reason
    return details


def _visible_enabled_providers_for_scope(db: Session, machine: Machine, scope: ScopeName) -> list[MachineProvider]:
    """Return providers that can observe one machine for one metric scope."""
    providers = (
        db.query(MachineProvider)
        .options(selectinload(MachineProvider.provisioners))
        .filter(MachineProvider.enabled.is_(True))
        .filter(MachineProvider.platform_id == machine.platform_id)
        .filter(MachineProvider.scope == scope)
        .order_by(MachineProvider.id.asc())
        .all()
    )
    return [provider for provider in providers if _provider_sees_machine(provider, machine)]


def _provider_sees_machine(provider: MachineProvider, machine: Machine) -> bool:
    """Return whether one provider can collect metrics for a machine."""
    provisioner_ids = {provisioner.id for provisioner in provider.provisioners}
    if not provisioner_ids:
        return True
    return machine.source_provisioner_id in provisioner_ids


def _load_metric_samples(
    db: Session,
    scope: ScopeName,
    provider_id: int,
    machine_id: int,
    limit: int,
) -> list[MachineCPUMetric | MachineRAMMetric | MachineDiskMetric]:
    """Return the latest stored metric samples for one scope."""
    metric_model = METRIC_MODELS[scope]
    return (
        db.query(metric_model)
        .filter(metric_model.provider_id == provider_id)
        .filter(metric_model.machine_id == machine_id)
        .order_by(metric_model.date.desc(), metric_model.id.desc())
        .limit(limit)
        .all()
    )


def _average_metric_value(values: list[float]) -> float:
    """Return the average utilization percent for one metric window."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _bounded_target(
    scope: ScopeName,
    raw_target: float,
    min_capacity: int | None,
    max_capacity: int | None,
) -> tuple[float | None, str | None]:
    """Round a raw target and apply catalog-bound recommendation rules."""
    rounded = _rounded_target(scope, raw_target)
    if rounded is None:
        return None, None
    if scope == "cpu":
        assert min_capacity is not None and max_capacity is not None
        if rounded < min_capacity:
            return float(min_capacity), "raised_to_min_cpu"
        if rounded > max_capacity:
            return None, "above_max_cpu"
    if scope == "ram":
        assert min_capacity is not None and max_capacity is not None
        if rounded < min_capacity:
            return float(min_capacity), "raised_to_min_ram"
        if rounded > max_capacity:
            return None, "above_max_ram"
    return rounded, None


def _rounded_target(scope: ScopeName, raw_target: float) -> float | None:
    """Round a raw target to the capacity units used by the scope."""
    if raw_target <= 0:
        return None
    if scope == "cpu":
        return float(max(1, ceil(raw_target)))
    if scope == "ram":
        return float(max(CAPACITY_STEP_MB, ceil(raw_target / CAPACITY_STEP_MB) * CAPACITY_STEP_MB))
    return float(max(CAPACITY_STEP_MB, ceil(raw_target / CAPACITY_STEP_MB) * CAPACITY_STEP_MB))


def _aggregate_optimization(scopes: dict[ScopeName, dict[str, object]]) -> tuple[OptimizationStatus, OptimizationAction]:
    """Aggregate scope-level decisions into one global optimization."""
    has_ambiguous_provider = any(scope["status"] == "ambiguous_provider" for scope in scopes.values())
    ok_scopes = [scope for scope in scopes.values() if scope["status"] == "ok"]
    actions = {scope["action"] for scope in ok_scopes}

    if has_ambiguous_provider and not ok_scopes:
        return "error", "unavailable"
    if has_ambiguous_provider:
        return "error", "mixed" if "scale_up" in actions and "scale_down" in actions else _action_from_set(actions)
    if not ok_scopes:
        return "partial", "insufficient_data"
    if any(scope["status"] != "ok" for scope in scopes.values()):
        return "partial", _action_from_set(actions)
    return "ready", _action_from_set(actions)


def _action_from_set(actions: set[object]) -> OptimizationAction:
    """Return the aggregated action for the set of scope actions."""
    if "scale_up" in actions and "scale_down" in actions:
        return "mixed"
    if "scale_up" in actions:
        return "scale_up"
    if "scale_down" in actions:
        return "scale_down"
    if actions:
        return "keep"
    return "insufficient_data"


def _effective_target(current_capacity: float | None, scope: dict[str, object]) -> float | None:
    """Return the actionable target capacity for one scope."""
    if current_capacity is None:
        return None
    if scope["status"] != "ok":
        return None
    if scope["action"] in {"scale_up", "scale_down"}:
        return float(scope["bounded_target_capacity"]) if scope["bounded_target_capacity"] is not None else None
    return float(current_capacity)


def _current_optimization_query(db: Session, machine_id: int):
    """Return the query used to load the optimization row."""
    query = db.query(MachineOptimization).filter(MachineOptimization.machine_id == machine_id)
    if db.get_bind().dialect.name != "sqlite":
        query = query.with_for_update()
    return query


def _optimization_snapshot_matches(current: MachineOptimization, snapshot: dict[str, object]) -> bool:
    """Return whether the calculated snapshot matches the stored current row."""
    return (
        current.status == snapshot["status"]
        and current.action == snapshot["action"]
        and current.window_size == snapshot["window_size"]
        and current.min_cpu == snapshot["min_cpu"]
        and current.max_cpu == snapshot["max_cpu"]
        and current.min_ram_mb == snapshot["min_ram_mb"]
        and current.max_ram_mb == snapshot["max_ram_mb"]
        and current.current_cpu == snapshot["current_cpu"]
        and current.current_ram_mb == snapshot["current_ram_mb"]
        and current.current_disk_mb == snapshot["current_disk_mb"]
        and current.target_cpu == snapshot["target_cpu"]
        and current.target_ram_mb == snapshot["target_ram_mb"]
        and current.target_disk_mb == snapshot["target_disk_mb"]
        and current.details == snapshot["details"]
    )
