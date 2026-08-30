"""Admin Zaptec sync endpoints (Epic 3 / Epic 4).

``sync/chargers`` mirrors devices; ``sync/sessions`` (P4) imports charging
history. ``status`` reports the last run of each kind for the health view.
Router-level ``require_admin``; writes add ``require_fetch``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain import periods
from ladelaug_avregning.domain.sync_runs import SyncRunRepo
from ladelaug_avregning.errors import DomainError
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_db,
    require_admin,
    require_fetch,
)
from ladelaug_avregning.zaptec.sync import ZaptecSync

router = APIRouter(prefix="/api/zaptec", dependencies=[Depends(require_admin)], tags=["zaptec"])


@router.post("/sync/chargers", dependencies=[Depends(require_fetch)])
async def sync_chargers(
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    return await ZaptecSync(db, config).sync_chargers(actor=actor)


@router.post("/sync/sessions", dependencies=[Depends(require_fetch)])
async def sync_sessions(
    from_: str | None = None,
    to: str | None = None,
    month: str | None = None,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    if month is not None:
        if not periods.valid_month(month):
            raise DomainError("bad_month", "month must be YYYY-MM")
        start, end = periods.month_bounds(month, config.timezone)
        date_from, date_to = start.date().isoformat(), end.date().isoformat()
    else:
        s, e = periods.month_bounds(periods.current_month(config.timezone), config.timezone)
        date_from = from_ or s.date().isoformat()
        date_to = to or e.date().isoformat()
    return await ZaptecSync(db, config).sync_sessions(
        date_from=date_from, date_to=date_to, actor=actor
    )


@router.get("/status")
async def zaptec_status(
    db: Database = Depends(get_db), config: AppConfig = Depends(get_config)
) -> dict[str, Any]:
    runs = SyncRunRepo(db)
    return {
        "enabled": config.zaptec.enabled,
        "installation_id": config.zaptec.installation_id or None,
        "last": {kind: runs.latest(kind) for kind in ("chargers", "sessions", "intervals")},
        "recent": runs.recent(limit=10),
        "failures": runs.failure_count(),
    }
