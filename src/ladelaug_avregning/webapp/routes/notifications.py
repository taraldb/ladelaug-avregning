"""Admin email-queue endpoints (Epic 10).

``process`` drains the queue — wire it to a cron (see README). ``GET`` lists
recent messages and the queue stats for the health view.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.email.sender import build_sender
from ladelaug_avregning.webapp.deps import get_config, get_db, require_admin, require_fetch

router = APIRouter(
    prefix="/api/notifications", dependencies=[Depends(require_admin)], tags=["notifications"]
)


@router.get("")
async def list_messages(limit: int = 50, db: Database = Depends(get_db)) -> dict[str, Any]:
    repo = NotificationRepo(db)
    return {"stats": repo.stats(), "messages": repo.recent(limit=min(limit, 200))}


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
