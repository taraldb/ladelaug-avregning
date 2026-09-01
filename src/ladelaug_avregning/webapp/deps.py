"""Shared FastAPI dependencies: resource accessors, auth, and RBAC gates.

``get_current_user`` resolves the session cookie on every request and re-checks
``disabled`` so a disabled account loses access immediately. ``require_admin`` /
``get_current_member`` are the role gates — admin routers mount ``require_admin``
at router level so new admin endpoints are protected by construction.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from ladelaug_avregning.audit import AuditContext, record_audit
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.sessions import SessionRepo
from ladelaug_avregning.domain.users import UserRepo
from ladelaug_avregning.errors import AuthError


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def require_fetch(request: Request) -> None:
    """CSRF guard: browsers cannot set this header cross-origin without a
    preflight our endpoints never grant. Mounted on every mutating route."""
    if request.headers.get("x-requested-with") != "fetch":
        raise AuthError("Missing X-Requested-With header", status=403, code="csrf")


async def get_current_user(request: Request) -> dict[str, Any]:
    db = get_db(request)
    config = get_config(request)
    token = request.cookies.get(config.auth.cookie_name)
    if not token:
        raise AuthError("Not authenticated", status=401)

    sessions = SessionRepo(db)
    session = sessions.get_valid(token)
    if session is None:
        raise AuthError("Not authenticated", status=401)

    # Downstream deps (get_current_member, forbid_view_as, /api/auth/me) read the
    # session's view_as_member_id from here without another lookup.
    request.state.session = session

    user = UserRepo(db).get(int(session["user_id"]))
    if user is None or user["disabled"]:
        await sessions.revoke(token)
        if user is not None:
            # Fires once per live session (the token is now gone), so a disabled
            # account leaves a trail without spamming the log.
            await record_audit(
                db,
                AuditContext(
                    actor_user_id=int(user["id"]),
                    actor_label=user["email"],
                    ip=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    actor_role=user["role"],
                ),
                event_type="user.session_revoked_disabled",
                entity_type="user",
                entity_id=int(user["id"]),
                summary=f"Session revoked mid-request: {user['email']} is disabled",
            )
        raise AuthError("Not authenticated", status=401)

    await sessions.touch(token, ttl_hours=config.auth.session_ttl_hours)
    return user


def get_audit_context(
    request: Request, user: dict[str, Any] = Depends(get_current_user)
) -> AuditContext:
    return AuditContext(
        actor_user_id=int(user["id"]),
        actor_label=user["email"],
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        actor_role=user["role"],
    )


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise AuthError("Admin access required", status=403)
    return user


def active_view_as(request: Request, user: dict[str, Any]) -> int | None:
    """The member id an admin is previewing the portal as, or ``None``.

    Only ever honoured for an admin — a stale ``view_as_member_id`` on a session
    whose user was since demoted is ignored."""
    if user["role"] != "admin":
        return None
    session = getattr(request.state, "session", None)
    if not session:
        return None
    member_id = session.get("view_as_member_id")
    return int(member_id) if member_id is not None else None


def get_current_member(request: Request, user: dict[str, Any] = Depends(get_current_user)) -> int:
    view_as = active_view_as(request, user)
    if view_as is not None:
        return view_as
    if user["member_id"] is None:
        raise AuthError("This endpoint is for members", status=403)
    return int(user["member_id"])


def forbid_view_as(request: Request, user: dict[str, Any] = Depends(get_current_user)) -> None:
    """Block a write while the caller is previewing the portal as a member —
    view-as is strictly read-only, so nothing can be changed on the member's
    account."""
    if active_view_as(request, user) is not None:
        raise AuthError(
            "Read-only while viewing the portal as a member",
            status=403,
            code="view_as_read_only",
        )
