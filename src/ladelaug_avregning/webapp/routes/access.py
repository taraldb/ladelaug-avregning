"""Admin charging-access status (US-305) + its notifications (US-1003 / US-1004).

Router-level ``require_admin``; the mutating route adds ``require_fetch``. This
records intent and notifies the member — it does not enforce anything on Zaptec
(Release 2 owns "Direct Zaptec access control").
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.access import AccessRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import NotFoundError
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_db,
    require_admin,
    require_fetch,
)
from ladelaug_avregning.webapp.schemas import AccessActionIn, AccessEventOut

router = APIRouter(prefix="/api/members", dependencies=[Depends(require_admin)], tags=["access"])


def _require_member(db: Database, member_id: int) -> None:
    if MemberRepo(db).get(member_id) is None:
        raise NotFoundError(f"member {member_id} not found")


@router.get("/{member_id}/access")
async def get_access(member_id: int, db: Database = Depends(get_db)) -> dict[str, Any]:
    _require_member(db, member_id)
    repo = AccessRepo(db)
    return {
        "member_id": member_id,
        "status": repo.current(member_id),
        "history": [AccessEventOut.from_row(r) for r in repo.history(member_id)],
    }


@router.post("/{member_id}/access", dependencies=[Depends(require_fetch)])
async def record_access(
    member_id: int,
    body: AccessActionIn,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    row = await AccessRepo(db).record(
        member_id,
        body.action,
        reason=body.reason,
        note=body.note,
        portal_url=config.zaptec.portal_url,
        actor=actor,
    )
    repo = AccessRepo(db)
    return {
        "member_id": member_id,
        "status": repo.current(member_id),
        "event": AccessEventOut.from_row(row),
        "history": [AccessEventOut.from_row(r) for r in repo.history(member_id)],
    }
