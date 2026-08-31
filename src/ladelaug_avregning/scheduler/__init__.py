"""In-process recurring-job scheduler.

A :class:`ladelaug_avregning.scheduler.runner.SchedulerRunner` task is started
from the FastAPI lifespan (``webapp/app.py``) when ``config.scheduler.enabled``
is set. It reads the ``job_schedules`` table every tick and runs any enabled job
whose ``next_run_at`` has passed — sequentially, so only one job touches SQLite
at a time. The job bodies in :mod:`ladelaug_avregning.scheduler.jobs` are thin
wrappers over the same coroutines the admin HTTP routes and the CLI already call.

Import ``jobs`` and ``runner`` directly (this package ``__init__`` stays empty to
avoid an import cycle with :mod:`ladelaug_avregning.domain.job_schedules`).
"""
