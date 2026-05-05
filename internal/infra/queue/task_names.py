"""Canonical Celery task names used across the runtimes."""

RUN_PROVIDER_TASK = "providers.run"
RUN_PROVISIONER_TASK = "provisioners.run"
SYNC_APPLICATION_TASK = "applications.sync"
DISPATCH_DUE_JOBS_TASK = "scheduler.dispatch_due_jobs"
DISPATCH_DUE_APPLICATION_SYNCS_TASK = "applications.dispatch_due_syncs"
