"""Admin user administration (Epic 1): provision and manage login identities.

Router-level ``require_admin`` gates the whole surface; mutating routes add
``require_fetch`` (CSRF). A login is either a pure administrator (``role="admin"``,
no ``member_id``) or a member's portal login (``role="member"`` linked 1:1 to a
member). Passwords are optional at creation — an account with no hash is entered
via a magic link or a password reset.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.users import UserRepo
from ladelaug_avregning.errors import DomainError, NotFoundError
from ladelaug_avregning.webapp.deps import get_audit_context, get_db, require_admin, require_fetch
from ladelaug_avregning.webapp.schemas import UserCreateIn, UserOut, UserSetPasswordIn

router = APIRouter(prefix="/api/users", dependencies=[Depends(require_admin)], tags=["users"])


def _require_user(repo: UserRepo, user_id: int) -> dict[str, Any]:
    row = repo.get(user_id)
    if row is None:
        raise NotFoundError(f"user {user_id} not found")
    return row


@router.get("")
async def list_users(db: Database = Depends(get_db)) -> dict[str, list[UserOut]]:
    return {"users": [UserOut.from_row(r) for r in UserRepo(db).list()]}


@router.post("", status_code=201, dependencies=[Depends(require_fetch)])
async def create_user(
    body: UserCreateIn,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> UserOut:
    repo = UserRepo(db)
    if body.member_id is not None and MemberRepo(db).get(body.member_id) is None:
        raise NotFoundError(f"member {body.member_id} not found")
    user_id = await repo.create(
        email=body.email,
        password=body.password,
        role=body.role,
        member_id=body.member_id,
        actor=actor,
    )
    return UserOut.from_row(_require_user(repo, user_id))


async def _set_disabled(user_id: int, disabled: bool, db: Database, actor: AuditContext) -> UserOut:
    repo = UserRepo(db)
    row = _require_user(repo, user_id)
    if disabled:
        if user_id == actor.actor_user_id:
            raise DomainError("cannot_disable_self", "You cannot disable your own account.")
        if row["role"] == "admin" and not row["disabled"]:
            other_admins = [
                u
                for u in repo.list()
                if u["role"] == "admin" and not u["disabled"] and u["id"] != user_id
            ]
            if not other_admins:
                raise DomainError("last_admin", "Cannot disable the last active administrator.")
    await repo.set_disabled(user_id, disabled, actor=actor)
    return UserOut.from_row(_require_user(repo, user_id))


@router.post("/{user_id}/disable", dependencies=[Depends(require_fetch)])
async def disable_user(
    user_id: int,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> UserOut:
    return await _set_disabled(user_id, True, db, actor)


@router.post("/{user_id}/enable", dependencies=[Depends(require_fetch)])
async def enable_user(
    user_id: int,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> UserOut:
    return await _set_disabled(user_id, False, db, actor)


@router.post("/{user_id}/password", dependencies=[Depends(require_fetch)])
async def set_user_password(
    user_id: int,
    body: UserSetPasswordIn,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, bool]:
    repo = UserRepo(db)
    _require_user(repo, user_id)
    await repo.set_password(user_id, body.password, actor=actor)
    return {"ok": True}
