"""The scheduler loop.

``SchedulerRunner.run_forever`` wakes every ``config.scheduler.tick_seconds``,
reads ``job_schedules``, and runs each enabled job whose ``next_run_at`` has
passed. Jobs run one after another (``await`` in a plain loop), so two jobs never
hit SQLite at once and a long job simply delays the next tick — there is no
overlap and no backlog. ``next_run_at`` is always recomputed forward from "now",
so missed slots are skipped rather than replayed.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from datetime import datetime
from typing import Any

from ladelaug_avregning import clock
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.job_schedules import JobScheduleRepo
from ladelaug_avregning.scheduler.jobs import JOBS

log = logging.getLogger(__name__)


async def run_job_once(db: Database, config: AppConfig, name: str) -> dict[str, Any]:
    """Run one job body with the ``running`` / ``ok`` / ``error`` bookkeeping and
    the forward ``next_run_at`` recompute. Shared by the loop and the manual
    ``POST /api/system/jobs/{name}/run`` endpoint. Never raises for a job failure
    — the outcome is in the returned dict and on the row."""
    repo = JobScheduleRepo(db)
    row = repo.get(name)
    cron = row["cron"] if row is not None else "*/10 * * * *"

    await repo.mark_started(name)
    started = time.monotonic()
    status, error, summary = "ok", None, {}
    try:
        summary = await JOBS[name](db, config)
        log.info("job %s ok: %s", name, summary)
    except Exception as exc:
        status, error = "error", repr(exc)
        log.exception("job %s failed", name)
    finally:
        duration_ms = int((time.monotonic() - started) * 1000)
        await repo.mark_finished(
            name,
            now=clock.now_utc(),
            status=status,
            error=error,
            duration_ms=duration_ms,
            cron=cron,
        )
    return {
        "name": name,
        "status": status,
        "error": error,
        "duration_ms": duration_ms,
        "summary": summary,
    }


class SchedulerRunner:
    def __init__(self, db: Database, config: AppConfig) -> None:
        self._db = db
        self._config = config

    async def run_forever(self) -> None:
        tick = self._config.scheduler.tick_seconds
        log.info("job scheduler started (tick=%ss)", tick)
        try:
            while True:
                try:
                    await self._tick()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("scheduler tick failed")
                await asyncio.sleep(tick)
        except asyncio.CancelledError:
            log.info("job scheduler stopped")
            raise

    async def _tick(self) -> None:
        for row in JobScheduleRepo(self._db).list():
            if not row["enabled"]:
                continue
            if _is_due(row["next_run_at"], clock.now_utc()):
                await run_job_once(self._db, self._config, row["name"])


def _is_due(next_run_at: str | None, now: datetime) -> bool:
    return next_run_at is None or next_run_at <= now.isoformat()


async def start(db: Database, config: AppConfig) -> asyncio.Task[None] | None:
    """Create the scheduler task when enabled; called from the FastAPI lifespan."""
    if not config.scheduler.enabled:
        return None
    return asyncio.create_task(SchedulerRunner(db, config).run_forever(), name="job-scheduler")


async def stop(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
