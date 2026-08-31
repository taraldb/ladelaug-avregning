"""The job registry.

Each entry is an async callable ``(db, config) -> dict`` (the dict is a summary
logged after the run). Every body delegates to the existing domain coroutine —
the same one the admin route and the CLI use — so there is one implementation of
each job, not three.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain import periods
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.email.sender import build_sender
from ladelaug_avregning.zaptec.sync import ZaptecSync

JobFn = Callable[[Database, AppConfig], Awaitable[dict[str, Any]]]


def _state_dir(config: AppConfig) -> Path:
    # Mirrors routes/notifications.py and __main__._cmd_drain_mail.
    if config.database.path == ":memory:":
        return Path("state")
    return Path(config.database.path).parent


async def drain_mail(db: Database, config: AppConfig) -> dict[str, Any]:
    sender = build_sender(config.email, state_dir=_state_dir(config))
    return await NotificationRepo(db).process_queue(sender)


async def low_balance_scan(db: Database, config: AppConfig) -> dict[str, Any]:
    return await NotificationRepo(db).scan_low_balances(actor=AuditContext.system())


async def zaptec_sync_sessions(db: Database, config: AppConfig) -> dict[str, Any]:
    if not config.zaptec.enabled:
        return {"skipped": "zaptec_disabled"}
    start, end = periods.month_bounds(periods.current_month(config.timezone), config.timezone)
    return await ZaptecSync(db, config).sync_sessions(
        date_from=start.date().isoformat(),
        date_to=end.date().isoformat(),
        actor=AuditContext.system(),
    )


JOBS: dict[str, JobFn] = {
    "drain_mail": drain_mail,
    "low_balance_scan": low_balance_scan,
    "zaptec_sync_sessions": zaptec_sync_sessions,
}

KNOWN_JOBS = frozenset(JOBS)
