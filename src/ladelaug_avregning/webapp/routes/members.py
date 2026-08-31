"""Admin member administration (Epic 2): records, status timeline, participation.

Router-level ``require_admin`` gates the whole surface; mutating routes add
``require_fetch`` (CSRF). Member-facing reads are Phase F's ``/api/me/*``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import NotFoundError
from ladelaug_avregning.webapp.deps import get_audit_context, get_db, require_admin, require_fetch
from ladelaug_avregning.webapp.schemas import (
    DepartureIn,
    MemberIn,
    MemberOut,
    MemberPatch,
    ParticipationChangeIn,
    ParticipationPeriodOut,
    StatusChangeIn,
    StatusPeriodOut,
)

router = APIRouter(prefix="/api/members", dependencies=[Depends(require_admin)], tags=["members"])


def _member_out(db: Database, repo: MemberRepo, row: dict[str, Any]) -> MemberOut:
    return MemberOut.from_row(
        row,
        status=repo.current_status(row["id"]),
        participates=repo.effective_participation(row["id"]),
        balance_ore=LedgerRepo(db).balance_ore(row["id"]),
    )


def _require_member(repo: MemberRepo, member_id: int) -> dict[str, Any]:
    row = repo.get(member_id)
    if row is None:
        raise NotFoundError(f"member {member_id} not found")
    return row


@router.post("", status_code=201, dependencies=[Depends(require_fetch)])
async def create_member(
    body: MemberIn,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> MemberOut:
    repo = MemberRepo(db)
    row = await repo.create(
        member_reference=body.member_reference,
        full_name=body.full_name,
        email=body.email,
        join_date=body.join_date,
        actor=actor,
    )
    return _member_out(db, repo, row)


@router.get("")
async def list_members(db: Database = Depends(get_db)) -> dict[str, list[MemberOut]]:
    repo = MemberRepo(db)
    status = repo.status_map()
    explicit = repo.explicit_participation_map()
    active = {mid for mid, s in status.items() if s == "active"}
    balances = LedgerRepo(db).balance_ore_map()

    def participates(member_id: int) -> bool | None:
        if member_id in explicit:
            return explicit[member_id]
        return True if member_id in active else None

    return {
        "members": [
            MemberOut.from_row(
                m,
                status=status.get(m["id"]),
                participates=participates(m["id"]),
                balance_ore=balances.get(m["id"], 0),
            )
            for m in repo.list()
        ]
    }


@router.get("/{member_id}")
async def get_member(member_id: int, db: Database = Depends(get_db)) -> MemberOut:
    repo = MemberRepo(db)
    return _member_out(db, repo, _require_member(repo, member_id))


@router.patch("/{member_id}", dependencies=[Depends(require_fetch)])
async def update_member(
    member_id: int,
    body: MemberPatch,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> MemberOut:
    repo = MemberRepo(db)
    row = await repo.update(member_id, actor=actor, **body.model_dump(exclude_unset=True))
    return _member_out(db, repo, row)


@router.post("/{member_id}/status", dependencies=[Depends(require_fetch)])
async def set_status(
    member_id: int,
    body: StatusChangeIn,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, StatusPeriodOut]:
    row = await MemberRepo(db).set_status(
        member_id,
        body.status,
        effective_from=body.effective_from,
        note=body.note,
        actor=actor,
    )
    return {"period": StatusPeriodOut.from_row(row)}


@router.get("/{member_id}/status-history")
async def status_history(
    member_id: int, db: Database = Depends(get_db)
) -> dict[str, list[StatusPeriodOut]]:
    repo = MemberRepo(db)
    _require_member(repo, member_id)
    return {"periods": [StatusPeriodOut.from_row(r) for r in repo.status_history(member_id)]}


@router.post("/{member_id}/participation", dependencies=[Depends(require_fetch)])
async def set_participation(
    member_id: int,
    body: ParticipationChangeIn,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, ParticipationPeriodOut]:
    row = await MemberRepo(db).set_participation(
        member_id,
        body.participates,
        effective_from=body.effective_from,
        reason=body.reason,
        actor=actor,
    )
    return {"period": ParticipationPeriodOut.from_row(row)}


@router.get("/{member_id}/departure-check")
async def departure_check(
    member_id: int,
    effective_date: str | None = Query(default=None),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    return MemberRepo(db).departure_check(member_id, effective_date=effective_date)


@router.post("/{member_id}/departure", dependencies=[Depends(require_fetch)])
async def process_departure(
    member_id: int,
    body: DepartureIn,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    return await MemberRepo(db).process_departure(
        member_id,
        effective_date=body.effective_date,
        refund=body.refund,
        refund_reference=body.refund_reference,
        actor=actor,
    )


@router.get("/{member_id}/participation-history")
async def participation_history(
    member_id: int, db: Database = Depends(get_db)
) -> dict[str, list[ParticipationPeriodOut]]:
    repo = MemberRepo(db)
    _require_member(repo, member_id)
    return {
        "periods": [
            ParticipationPeriodOut.from_row(r) for r in repo.participation_history(member_id)
        ]
    }
