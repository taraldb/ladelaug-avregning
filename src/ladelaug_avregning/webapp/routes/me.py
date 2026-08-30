"""Member self-service (US-104, member-facing US-501).

Everything here resolves the member id from the session via
``Depends(get_current_member)`` — never a path or query parameter — so a member
can only ever see their own record, balance, ledger, and status. A pure admin
(no linked member) gets 403; an anonymous caller gets 401.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import NotFoundError
from ladelaug_avregning.money import nok_to_ore
from ladelaug_avregning.webapp.deps import get_current_member, get_db
from ladelaug_avregning.webapp.schemas import LedgerTxnOut, MemberOut, StatusPeriodOut

router = APIRouter(prefix="/api/me", tags=["me"])


@router.get("")
async def me(
    member_id: int = Depends(get_current_member), db: Database = Depends(get_db)
) -> MemberOut:
    repo = MemberRepo(db)
    row = repo.get(member_id)
    if row is None:
        raise NotFoundError(f"member {member_id} not found")
    return MemberOut.from_row(
        row,
        status=repo.current_status(member_id),
        participates=repo.effective_participation(member_id),
    )


@router.get("/balance")
async def my_balance(
    member_id: int = Depends(get_current_member), db: Database = Depends(get_db)
) -> dict[str, Any]:
    bal = LedgerRepo(db).balance(member_id)
    return {"member_id": member_id, "balance_nok": str(bal), "balance_ore": nok_to_ore(bal)}


@router.get("/ledger")
async def my_ledger(
    member_id: int = Depends(get_current_member),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    repo = LedgerRepo(db)
    rows, total = repo.list(member_id, limit=limit, offset=offset)
    bal = repo.balance(member_id)
    return {
        "transactions": [LedgerTxnOut.from_row(r) for r in rows],
        "total": total,
        "balance_nok": str(bal),
        "balance_ore": nok_to_ore(bal),
    }


@router.get("/status")
async def my_status(
    member_id: int = Depends(get_current_member), db: Database = Depends(get_db)
) -> dict[str, Any]:
    repo = MemberRepo(db)
    return {
        "status": repo.current_status(member_id),
        "participates": repo.effective_participation(member_id),
        "history": [StatusPeriodOut.from_row(r) for r in repo.status_history(member_id)],
    }
