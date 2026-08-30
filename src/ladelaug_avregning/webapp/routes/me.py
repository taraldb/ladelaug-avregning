"""Member self-service (US-104, member-facing US-501).

Everything here resolves the member id from the session via
``Depends(get_current_member)`` — never a path or query parameter — so a member
can only ever see their own record, balance, ledger, and status. A pure admin
(no linked member) gets 403; an anonymous caller gets 401.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response

from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain import periods
from ladelaug_avregning.domain.charging import ChargingRepo
from ladelaug_avregning.domain.forecast import ForecastRepo
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.errors import DomainError, NotFoundError
from ladelaug_avregning.money import nok_to_ore
from ladelaug_avregning.reports import html_to_pdf, render_member_report
from ladelaug_avregning.webapp.deps import get_config, get_current_member, get_db
from ladelaug_avregning.webapp.schemas import (
    LedgerTxnOut,
    MemberConsumptionOut,
    MemberForecastOut,
    MemberOut,
    StatusPeriodOut,
)

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


@router.get("/forecast")
async def my_forecast(
    member_id: int = Depends(get_current_member), db: Database = Depends(get_db)
) -> MemberForecastOut:
    return MemberForecastOut.from_forecast(ForecastRepo(db).member_forecast(member_id))


@router.get("/consumption")
async def my_consumption(
    member_id: int = Depends(get_current_member),
    month: str | None = Query(default=None),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> MemberConsumptionOut:
    resolved = month or periods.current_month(config.timezone)
    if not periods.valid_month(resolved):
        raise DomainError("bad_month", "month must be YYYY-MM")
    charging = ChargingRepo(db, tz=config.timezone)
    return MemberConsumptionOut(
        member_id=member_id,
        month=resolved,
        consumption_kwh=str(charging.member_consumption(member_id, resolved)),
        session_count=charging.member_session_count(member_id, resolved),
    )


@router.get("/settlements")
async def my_settlements(
    member_id: int = Depends(get_current_member),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    repo = SettlementRepo(db, tz=config.timezone)
    out = []
    for s in repo.posted_for_member(member_id):
        entry = repo.member_entry(int(s["id"]), member_id)
        if entry is None:
            continue
        m = entry["member"]
        out.append(
            {
                "settlement_id": s["id"],
                "period_month": s["period_month"],
                "posted_at": s["posted_at"],
                "consumption_kwh": m["consumption_kwh"],
                "charge_nok": m["charge_nok"],
                "balance_after_nok": m["balance_after_nok"],
                "report_url": f"/api/me/settlements/{s['id']}/report",
            }
        )
    return {"settlements": out}


def _my_report_html(settlement_id: int, member_id: int, db: Database, config: AppConfig) -> str:
    repo = SettlementRepo(db, tz=config.timezone)
    row = repo.get(settlement_id)
    if row is None or row["status"] != "posted":
        raise NotFoundError(f"settlement {settlement_id} not found")
    entry = repo.member_entry(settlement_id, member_id)
    if entry is None:
        raise DomainError("not_in_settlement", "You are not part of this settlement.")
    forecast = ForecastRepo(db).member_forecast(member_id)
    return render_member_report(entry["result"], entry["member"], forecast)


@router.get("/settlements/{settlement_id}/report", response_class=HTMLResponse)
async def my_settlement_report(
    settlement_id: int,
    member_id: int = Depends(get_current_member),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> HTMLResponse:
    return HTMLResponse(_my_report_html(settlement_id, member_id, db, config))


@router.get("/settlements/{settlement_id}/report.pdf")
async def my_settlement_report_pdf(
    settlement_id: int,
    member_id: int = Depends(get_current_member),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> Response:
    html = _my_report_html(settlement_id, member_id, db, config)
    return Response(
        content=html_to_pdf(html),
        media_type="application/pdf",
        headers={"Content-Disposition": (f'inline; filename="avregning-{settlement_id}.pdf"')},
    )
