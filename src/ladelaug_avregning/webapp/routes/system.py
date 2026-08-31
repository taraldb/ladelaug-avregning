"""Operational health for admins (US-1104): Zaptec sync state, email queue,
failed jobs, versions.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning import __version__
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.access import AccessRepo
from ladelaug_avregning.domain.forecast import ForecastRepo
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.domain.sync_runs import SyncRunRepo
from ladelaug_avregning.webapp.deps import get_config, get_db, require_admin

router = APIRouter(prefix="/api/system", dependencies=[Depends(require_admin)], tags=["system"])


@router.get("/health")
async def health(
    db: Database = Depends(get_db), config: AppConfig = Depends(get_config)
) -> dict[str, Any]:
    from ladelaug_avregning.reports.pdf import PDF_AVAILABLE, PDF_IMPORT_ERROR

    runs = SyncRunRepo(db)
    notif = NotificationRepo(db)
    schema_version = db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[
        0
    ]
    email_stats = notif.stats()
    warned_total = db.connection.execute(
        "SELECT COUNT(*) FROM low_balance_notifications"
    ).fetchone()[0]
    members_below = sum(
        1 for f in ForecastRepo(db).all_member_forecasts() if f["available"] and f["low_balance"]
    )
    low_balance = {"warned_total": int(warned_total), "members_below": members_below}
    srepo = SettlementRepo(db, tz=config.timezone)
    corrections = {
        "settlements_with_pending": sum(
            1
            for s in srepo.list()
            if s["status"] == "posted" and srepo.has_pending_correction(int(s["id"]))
        )
    }
    access = {"disabled": AccessRepo(db).disabled_count()}
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
        "pdf": {"available": PDF_AVAILABLE, "error": PDF_IMPORT_ERROR},
        "low_balance": low_balance,
        "corrections": corrections,
        "access": access,
        "failed_jobs": email_stats["failed"] + zaptec["failed_runs"],
        "ok": email_stats["failed"] == 0 and zaptec["failed_runs"] == 0,
    }
