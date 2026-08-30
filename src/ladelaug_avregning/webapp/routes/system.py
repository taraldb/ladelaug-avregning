"""Operational health for admins (US-1104): Zaptec sync state, email queue,
failed jobs, versions.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning import __version__
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.domain.sync_runs import SyncRunRepo
from ladelaug_avregning.webapp.deps import get_config, get_db, require_admin

router = APIRouter(prefix="/api/system", dependencies=[Depends(require_admin)], tags=["system"])


@router.get("/health")
async def health(
    db: Database = Depends(get_db), config: AppConfig = Depends(get_config)
) -> dict[str, Any]:
    runs = SyncRunRepo(db)
    notif = NotificationRepo(db)
    schema_version = db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
        0
    ]
    email_stats = notif.stats()
    zaptec = {
        "enabled": config.zaptec.enabled,
        "installation_id": config.zaptec.installation_id or None,
        "last": {k: runs.latest(k) for k in ("chargers", "sessions", "intervals")},
        "failed_runs": runs.failure_count(),
    }
    return {
        "version": __version__,
        "schema_version": schema_version,
        "zaptec": zaptec,
        "email": email_stats,
        "failed_jobs": email_stats["failed"] + zaptec["failed_runs"],
        "ok": email_stats["failed"] == 0 and zaptec["failed_runs"] == 0,
    }
