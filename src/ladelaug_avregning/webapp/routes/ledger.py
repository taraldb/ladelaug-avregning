"""Admin financial ledger (Epic 5): balance, transaction list, payments,
reversals, and manual adjustments. Every write goes through ``LedgerRepo``, which
pairs each append-only row with an audit event in one transaction.

No router prefix — the paths straddle ``/api/members/...`` and
``/api/ledger-transactions/...`` (mirrors ``routes/audit.py``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import NotFoundError
from ladelaug_avregning.money import nok_to_ore
from ladelaug_avregning.webapp.deps import get_audit_context, get_db, require_admin, require_fetch
from ladelaug_avregning.webapp.schemas import AdjustmentIn, BalanceOut, LedgerTxnOut, PaymentIn

router = APIRouter(dependencies=[Depends(require_admin)], tags=["ledger"])


def _require_member(db: Database, member_id: int) -> None:
    if MemberRepo(db).get(member_id) is None:
        raise NotFoundError(f"member {member_id} not found")


@router.get("/api/members/{member_id}/balance")
async def get_balance(member_id: int, db: Database = Depends(get_db)) -> BalanceOut:
    _require_member(db, member_id)
    bal = LedgerRepo(db).balance(member_id)
    return BalanceOut(member_id=member_id, balance_nok=str(bal), balance_ore=nok_to_ore(bal))


@router.get("/api/members/{member_id}/ledger")
async def list_ledger(
    member_id: int,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    _require_member(db, member_id)
    repo = LedgerRepo(db)
    rows, total = repo.list(member_id, limit=limit, offset=offset)
    bal = repo.balance(member_id)
    return {
        "transactions": [LedgerTxnOut.from_row(r) for r in rows],
        "total": total,
        "balance_nok": str(bal),
        "balance_ore": nok_to_ore(bal),
    }


@router.post(
    "/api/members/{member_id}/payments",
    status_code=201,
    dependencies=[Depends(require_fetch)],
)
async def record_payment(
    member_id: int,
    body: PaymentIn,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> LedgerTxnOut:
    row = await LedgerRepo(db).record_payment(
        member_id=member_id,
        amount=body.amount,
        value_date=body.value_date or clock.today_oslo().isoformat(),
        reference=body.reference,
        actor=actor,
    )
    return LedgerTxnOut.from_row(row)


@router.post(
    "/api/members/{member_id}/adjustments",
    status_code=201,
    dependencies=[Depends(require_fetch)],
)
async def record_adjustment(
    member_id: int,
    body: AdjustmentIn,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> LedgerTxnOut:
    row = await LedgerRepo(db).adjust(
        member_id=member_id,
        direction=body.direction,
        amount=body.amount,
        reason=body.reason,
        reference=body.reference,
        actor=actor,
    )
    return LedgerTxnOut.from_row(row)


@router.post(
    "/api/ledger-transactions/{txn_id}/reverse",
    status_code=201,
    dependencies=[Depends(require_fetch)],
)
async def reverse_payment(
    txn_id: int,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> LedgerTxnOut:
    row = await LedgerRepo(db).reverse_payment(txn_id=txn_id, actor=actor)
    return LedgerTxnOut.from_row(row)
