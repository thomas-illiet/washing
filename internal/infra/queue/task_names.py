"""Canonical Celery task names used across the runtimes."""

RUN_PROVIDER_TASK = "providers.run"
RUN_PROVISIONER_TASK = "provisioners.run"
SYNC_APPLICATION_INVENTORY_DISCOVERY_TASK = "applications.sync_inventory_discovery"
DISPATCH_DUE_APPLICATION_METRICS_SYNCS_TASK = "applications.dispatch_due_metrics_syncs"
SYNC_APPLICATION_METRICS_TASK = "applications.sync_metrics"
DISPATCH_DUE_MACHINE_PROVISIONER_JOBS_TASK = "scheduler.dispatch_due_machine_provisioner_jobs"
