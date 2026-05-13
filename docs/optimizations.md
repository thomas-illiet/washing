# Machine Optimizations

Machine optimizations are versioned capacity suggestions for one machine. They compare the machine's current flavor with recent CPU, RAM, and disk metrics, then expose a current optimization plus historical revisions through the API.

## What the feature answers

For each machine, the service answers:

- whether the current CPU, RAM, and disk allocation should stay as-is
- whether CPU or RAM should scale up or down
- whether disk should scale up
- whether an optimization is unavailable because the data or provider setup is incomplete

Disk optimizations are conservative: disk can scale up when pressure is high, but it is not proposed for downscale.

## Inputs

The optimization engine uses:

- the current machine flavor from `machines.cpu`, `machines.ram_mb`, and `machines.disk_mb`
- exactly one visible enabled metric provider per scope: `cpu`, `ram`, and `disk`
- the latest `FLAVOR_OPTIMIZATION_WINDOW_SIZE` metric samples for each scope
- configured CPU and RAM bounds from `FLAVOR_OPTIMIZATION_MIN_*` and `FLAVOR_OPTIMIZATION_MAX_*`

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
| `GET` | `/v1/machines/optimizations` | List optimization revisions across machines with pagination and filters. |
| `POST` | `/v1/machines/optimizations/{optimization_id}/acknowledge` | Mark one optimization revision as acknowledged. |
| `GET` | `/v1/machines/{machine_id}/optimizations` | Read the current optimization revision. |
| `GET` | `/v1/machines/{machine_id}/optimizations/history` | Read all revisions, including the current one. |
| `POST` | `/v1/machines/{machine_id}/optimizations/recalculate` | Enqueue an on-demand recalculation. |

With OIDC enabled, read endpoints require the read role. Acknowledgement and recalculation endpoints require the admin role.

If a machine exists but no optimization has been computed yet, the current optimization endpoint returns `404` with `optimization not computed yet`.

The global list endpoint returns current optimizations by default. Pass `current_only=false` to include older revisions. It supports filters for `platform_id`, `machine_id`, `application`, `environment`, `region`, `status`, `action`, and `acknowledged`.

Acknowledgement is idempotent and records `acknowledged_at` plus `acknowledged_by` when an authenticated principal is available.

## Optimization Status

The top-level `status` summarizes whether the optimization can be trusted as a complete machine-level answer.

| Status | Meaning |
| --- | --- |
| `ready` | All scopes were evaluated successfully. |
| `partial` | At least one scope could not be evaluated because provider or metric data is missing. |
| `error` | At least one scope is ambiguous, usually because multiple visible enabled providers match the same machine and scope. |

The top-level `action` summarizes the scope actions:

| Action | Meaning |
| --- | --- |
| `scale_up` | At least one scope needs more capacity, and none needs less. |
| `scale_down` | At least one CPU or RAM scope can shrink, and none needs more. |
| `mixed` | Some scopes want to scale up while others want to scale down. |
| `keep` | Evaluated scopes should stay at the current capacity. |
| `insufficient_data` | No scope has enough usable data yet. |
| `unavailable` | No actionable optimization can be produced. |

## Scope Details

Each optimization includes a `details` object keyed by `cpu`, `ram`, and `disk`.

| Field | Meaning |
| --- | --- |
| `provider_id` | Provider used for that scope, or `null` when no single provider can be selected. |
| `status` | Scope status: `ok`, `missing_provider`, `ambiguous_provider`, `insufficient_data`, or `missing_current_capacity`. |
| `samples_used` | Number of metric samples loaded for the scope. |
| `last_metric_date` | Newest metric sample date used for the scope. |
| `stats` | Average, p95, and max across the loaded sample window. |
| `current_capacity` | Current machine CPU, RAM, or disk capacity. |
| `raw_target_capacity` | Unrounded target calculated from p95 pressure and target utilization. |
| `bounded_target_capacity` | Rounded and bounded target used for decisions. |
| `action` | Scope action: `scale_up`, `scale_down`, `keep`, `insufficient_data`, or `unavailable`. |
| `reason_code` | Machine-readable explanation for the scope decision. |

Common `reason_code` values include:

- `no_provider`
- `ambiguous_provider`
- `missing_current_capacity`
- `insufficient_points`
- `pressure_high`
- `pressure_low`
- `within_hysteresis`
- `raised_to_min_cpu`
- `capped_by_max_cpu`
- `raised_to_min_ram`
- `capped_by_max_ram`

## Calculation Rules

The engine uses a target utilization of `65%`.

For each scope with enough samples:

1. Sort the latest sample window and compute average, p95, and max.
2. Compute `raw_target_capacity = current_capacity * p95 / 65`.
3. Round the target by capacity type:
   - CPU rounds up to whole cores.
   - RAM rounds up to 1024 MB increments.
   - Disk rounds up to 10240 MB increments.
4. Apply CPU and RAM min/max bounds.
5. Propose scale-up when `p95 >= 85` or `max >= 95`, and the bounded target is more than `10%` above current capacity.
6. Propose CPU or RAM scale-down when `p95 <= 40` and `max <= 60`, and the bounded target is more than `20%` below current capacity.
7. Otherwise, keep the current capacity.

For `keep`, the public target remains the current capacity. For unavailable or insufficient scopes, the public target is `null`.

## Versioning

Optimizations are stored in `machine_optimizations`.

- one machine has only one current row with `is_current=true`
- old rows remain available as history with `is_current=false`
- `revision` increases when the calculated snapshot changes
- if a recalculation produces the same snapshot, the current row is updated in place with a new `computed_at`
- each revision stores the window size and CPU/RAM bounds used to compute it

This means configuration changes can create a new revision even if the visible target capacities stay the same.

## Operational Checklist

When optimizations are missing or partial:

- confirm the machine has current CPU, RAM, and disk flavor values
- confirm each needed scope has exactly one enabled visible provider
- confirm metric collection has produced at least `FLAVOR_OPTIMIZATION_WINDOW_SIZE` samples per scope
- run `POST /v1/machines/{machine_id}/optimizations/recalculate` after fixing provider visibility or optimization settings
- inspect `GET /v1/machines/{machine_id}/optimizations/history` to compare revisions

See [Configuration](./configuration.md#machine-optimization-settings), [Operations](./operations.md#machine-optimization-projection), and [Celery Task Map](./celery-task-map.md) for related runtime details.
