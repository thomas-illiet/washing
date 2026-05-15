# Machine Optimizations

Machine optimizations are current capacity suggestions for one machine. They compare the current machine flavor with recent CPU, RAM, and disk utilization metrics, then expose one current recommendation through the API.

## What the feature answers

For each machine, the service answers:

- whether CPU, RAM, and disk should stay as-is
- whether CPU or RAM should scale up or down
- whether disk should scale up
- whether a resource cannot be evaluated because provider setup or metric data is missing

Disk optimizations are conservative: disk can scale up when pressure is high, but it is never proposed for downscale.

## Inputs

The optimization engine uses:

- the current machine flavor from `machines.cpu`, `machines.ram_mb`, and `machines.disk_mb`
- exactly one visible enabled metric provider per scope: `cpu`, `ram`, and `disk`
- up to the latest `FLAVOR_OPTIMIZATION_WINDOW_SIZE` metric samples for each scope
- configured CPU and RAM bounds from `FLAVOR_OPTIMIZATION_MIN_*` and `FLAVOR_OPTIMIZATION_MAX_*`

CPU and RAM minimum bounds are actionable: when the calculated target falls below the configured minimum, the recommendation is raised to that minimum. CPU and RAM maximum bounds are catalog guards: when the calculated target is above the configured maximum, the recommendation keeps the current capacity and reports `above_max_cpu` or `above_max_ram`.

CPU and RAM samples are expected to be daily p95 utilization percentages already stored in the database. Disk samples are expected to be disk utilization percentages.

A provider is visible to a machine when it belongs to the same platform and either:

- it is not attached to specific provisioners, so it can observe all machines on the platform
- it is attached to the provisioner that discovered the machine

## Refresh Triggers

Optimizations refresh automatically when:

- inventory creates a new machine
- inventory detects a machine flavor change
- a metric collection task stores a machine metric sample

They can also be refreshed manually:

```http
POST /v1/machines/{machine_id}/optimizations/recalculate
```

Manual recalculation enqueues the `machines.recalculate_optimizations` Celery task and returns `202 Accepted` with a `task_id`.

## API Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/v1/machines/optimizations` | List current optimizations across machines with pagination and filters. |
| `GET` | `/v1/machines/{machine_id}/optimizations` | Read the current optimization. |
| `POST` | `/v1/machines/{machine_id}/optimizations/recalculate` | Enqueue an on-demand recalculation. |

The optimization response is intentionally compact. Each response contains top-level recommendation metadata and a `resources` object keyed by `cpu`, `ram`, and `disk`.

Each resource exposes:

| Field | Meaning |
| --- | --- |
| `status` | Resource status: `ok`, `missing_provider`, `ambiguous_provider`, `insufficient_data`, or `missing_current_capacity`. |
| `action` | Resource action: `scale_up`, `scale_down`, `keep`, `insufficient_data`, or `unavailable`. |
| `current` | Current capacity from inventory. |
| `recommended` | Recommended capacity, or `null` when the resource is not calculable. |
| `unit` | `cores` for CPU, `mb` for RAM and disk. |
| `utilization_percent` | Average utilization percent used for the recommendation. |
| `reason` | Machine-readable explanation such as `limited_history`, `pressure_high`, `pressure_low`, `raised_to_min_cpu`, `above_max_ram`, `no_samples`, or `no_provider`. |

With OIDC enabled, read endpoints require the read role. Acknowledgement and recalculation endpoints require the admin role.

If a machine exists but no optimization has been computed yet, the current optimization endpoint returns `404` with `optimization not computed yet`.

The global list endpoint supports filters for `platform_id`, `machine_id`, `application`, `environment`, `region`, `status`, and `action`.

## Optimization Status

The top-level `status` summarizes whether the optimization can be trusted as a complete machine-level answer.

| Status | Meaning |
| --- | --- |
| `ready` | All resources were evaluated successfully. |
| `partial` | At least one resource could not be evaluated because provider, metric, or current capacity data is missing. |
| `error` | At least one resource is ambiguous, usually because multiple visible enabled providers match the same machine and scope. |

The top-level `action` summarizes the resource actions:

| Action | Meaning |
| --- | --- |
| `scale_up` | At least one resource needs more capacity, and none needs less. |
| `scale_down` | At least one CPU or RAM resource can shrink, and none needs more. |
| `mixed` | Some resources want to scale up while others want to scale down. |
| `keep` | Evaluated resources should stay at the current capacity. |
| `insufficient_data` | No resource has usable metric data yet. |
| `unavailable` | No actionable optimization can be produced. |

## Calculation Rules

The engine uses a target utilization of `65%`.

For each resource:

1. Load up to the latest configured sample window.
2. If no sample exists, mark the resource as `insufficient_data`.
3. If at least one sample exists, compute `utilization_percent` as the average of the available sample values.
4. If fewer samples than `FLAVOR_OPTIMIZATION_WINDOW_SIZE` are available, still calculate and expose `limited_history` as the reason unless a CPU/RAM catalog bound is the more specific reason.
5. Compute `raw_target_capacity = current_capacity * utilization_percent / 65`.
6. Round the target by capacity type:
   - CPU rounds up to whole cores.
   - RAM rounds up to `1024 MB` increments.
   - Disk rounds up to `1024 MB` increments.
7. Apply CPU and RAM bounds: raise targets below the minimum, and keep current capacity when targets exceed the maximum.
8. Propose scale-up when utilization is at least `85%` and the target is more than `10%` above current capacity.
9. Propose CPU or RAM scale-down when utilization is at most `40%` and the target is more than `20%` below current capacity.
10. Otherwise, keep the current capacity.

For `keep`, the recommended capacity remains the current capacity. For unavailable or insufficient resources, the recommended capacity is `null`.

## Storage

Optimizations are stored in `machine_optimizations`.

- one machine has only one optimization row
- if a recalculation produces the same snapshot, the row is updated in place with a new `computed_at`
- if a recalculation changes the snapshot, the same row is updated in place
- each row stores the window size and CPU/RAM bounds used internally to compute it

This means configuration changes apply to the next refresh and replace the stored recommendation for that machine.

## Operational Checklist

When optimizations are missing or partial:

- confirm the machine has current CPU, RAM, and disk flavor values
- confirm each needed scope has exactly one enabled visible provider
- confirm metric collection has produced at least one sample for each calculable scope
- run `POST /v1/machines/{machine_id}/optimizations/recalculate` after fixing provider visibility or optimization settings

See [Configuration](./configuration.md#machine-optimization-settings), [Operations](./operations.md#machine-optimization-projection), and [Celery Task Map](./celery-task-map.md) for related runtime details.
