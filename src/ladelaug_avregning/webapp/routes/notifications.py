"""Admin email-queue endpoints (Epic 10).

``process`` drains the queue — wire it to a cron (see README). ``GET`` lists
recent messages and the queue stats for the health view.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.email.sender import build_sender
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_db,
    require_admin,
    require_fetch,
)

router = APIRouter(
    prefix="/api/notifications", dependencies=[Depends(require_admin)], tags=["notifications"]
)


@router.get("")
async def list_messages(limit: int = 50, db: Database = Depends(get_db)) -> dict[str, Any]:
    repo = NotificationRepo(db)
    return {"stats": repo.stats(), "messages": repo.recent(limit=min(limit, 200))}


@router.post("/{message_id}/requeue", dependencies=[Depends(require_fetch)])
async def requeue_message(
    message_id: int,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    """Put one ``failed``/``sent`` message back on the queue (US-1002). Enqueue
    only — drain with ``/process``. 404 unknown id, 422 ``not_requeueable``."""
    return {"message": await NotificationRepo(db).requeue(message_id, actor=actor)}


@router.post("/process", dependencies=[Depends(require_fetch)])
async def process_queue(
    limit: int = 50,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    state_dir = (
        Path(config.database.path).parent if config.database.path != ":memory:" else Path("state")
    )
    sender = build_sender(config.email, state_dir=state_dir)
    return await NotificationRepo(db).process_queue(sender, limit=min(limit, 200))


@router.post("/low-balance-scan", dependencies=[Depends(require_fetch)])
async def low_balance_scan(
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, int]:
    """Enqueue low-balance warning emails (US-805). Mirrors ``/process`` — wire
    it to a cron; drain the queue afterwards with ``/process``."""
    return await NotificationRepo(db).scan_low_balances(actor=actor)
