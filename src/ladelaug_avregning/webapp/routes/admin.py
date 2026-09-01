"""Admin-only utilities that don't belong to a single resource.

``view-as`` lets an admin browse the member portal (``/api/me/*`` + the SPA's
"Min konto") exactly as a chosen member sees it, **read-only**: the target is
stamped on the admin's own session row, ``get_current_member`` honours it, and
``forbid_view_as`` rejects every ``/api/me`` write while it is active. It never
hands the admin the member's session — no email links, no password reset.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from ladelaug_avregning.audit import AuditContext, record_audit
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.sessions import SessionRepo
from ladelaug_avregning.errors import NotFoundError
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_current_user,
    get_db,
    require_admin,
    require_fetch,
)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


def _session_token(request: Request, config: AppConfig) -> str | None:
    return request.cookies.get(config.auth.cookie_name)


@router.post("/view-as/{member_id}", dependencies=[Depends(require_fetch)])
async def start_view_as(
    member_id: int,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    member = MemberRepo(db).get(member_id)
    if member is None:
        raise NotFoundError(f"member {member_id} not found")

    token = _session_token(request, config)
    if token:
        await SessionRepo(db).set_view_as(token, member_id)
    await record_audit(
        db,
        actor,
        event_type="admin.view_as_started",
        entity_type="member",
        entity_id=member_id,
        summary=(
            f"{user['email']} started viewing the portal as "
            f"{member['full_name']} ({member['member_reference']})"
        ),
    )
    return {"member_id": member_id, "member_name": member["full_name"]}


@router.delete("/view-as", dependencies=[Depends(require_fetch)])
async def stop_view_as(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    token = _session_token(request, config)
    session = getattr(request.state, "session", None)
    previous = session.get("view_as_member_id") if session else None
    if token:
        await SessionRepo(db).set_view_as(token, None)
    if previous is not None:
        await record_audit(
            db,
            actor,
            event_type="admin.view_as_stopped",
            entity_type="member",
            entity_id=int(previous),
            summary=f"{user['email']} stopped viewing the portal as member {int(previous)}",
        )
    return {"ok": True}
