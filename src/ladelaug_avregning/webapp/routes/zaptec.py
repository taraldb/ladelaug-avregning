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
from ladelaug_avregning.domain.sync_runs import SyncRunRepo
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
