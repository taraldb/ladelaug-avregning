"""Admin-only read access to the append-only audit log (US-1101/1102/1103).

The write path lives in ``audit.py`` / ``AuditRepo``; this router is the query
surface: a filtered, paginated list plus per-event lookup. Mounted under a
router-level ``require_admin`` so members and anonymous callers get 403/401.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.audit_repo import AuditRepo
from ladelaug_avregning.errors import NotFoundError
from ladelaug_avregning.webapp.deps import get_db, require_admin

router = APIRouter(dependencies=[Depends(require_admin)], tags=["audit"])

SortColumn = Literal["occurred_at", "id", "event_type"]
SortDir = Literal["asc", "desc"]


@router.get("/api/audit-events")
async def list_audit_events(
    event_type: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    sort_by: SortColumn = "occurred_at",
    sort_dir: SortDir = "desc",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    repo = AuditRepo(db)
    events, total = repo.list_audit_events(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )
    return {"events": events, "total": total, "counts": repo.count_by_type()}


@router.get("/api/audit-events/{event_id}")
async def get_audit_event(event_id: int, db: Database = Depends(get_db)) -> dict[str, Any]:
    event = AuditRepo(db).get_audit_event(event_id)
    if event is None:
        raise NotFoundError("audit event not found")
    return {"event": event}
