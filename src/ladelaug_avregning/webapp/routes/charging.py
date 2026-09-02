"""Admin views over imported charging data (Epic 4 / US-304).

``consumption`` and ``unassigned`` feed the settlement freeze step; ``reresolve``
recomputes member attribution after an assignment gap is filled.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain import periods
from ladelaug_avregning.domain.charging import ChargingRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.errors import DomainError
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_db,
    require_admin,
    require_fetch,
)
from ladelaug_avregning.webapp.schemas import ChargingHistoryMonthOut, ChargingHistoryOut

router = APIRouter(prefix="/api/charging", dependencies=[Depends(require_admin)], tags=["charging"])


def _month_or_400(month: str) -> str:
    if not periods.valid_month(month):
        raise DomainError("bad_month", "month must be YYYY-MM")
    return month


@router.get("/sessions")
async def list_sessions(
    month: str,
    member_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    repo = ChargingRepo(db, tz=config.timezone)
    rows, total = repo.list_sessions(
        _month_or_400(month), member_id=member_id, limit=min(limit, 500), offset=offset
    )
    return {"month": month, "total": total, "sessions": rows}


@router.get("/consumption")
async def consumption(
    month: str,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    repo = ChargingRepo(db, tz=config.timezone)
    _month_or_400(month)
    by_member = repo.consumption_by_member(month)
    return {
        "month": month,
        "total_kwh": str(repo.total_kwh(month)),
        "unassigned_kwh": str(repo.unassigned_total_kwh(month)),
        "by_member": [
            {"member_id": mid, "energy_kwh": str(kwh)} for mid, kwh in sorted(by_member.items())
        ],
    }


@router.get("/history")
async def history(
    months: int = Query(default=12, ge=1, le=24),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> ChargingHistoryOut:
    """Rolling per-month strip for the admin "Forbruk" page: metered kWh split
    into assigned vs unassigned, the grid total, and — for months whose
    settlement is posted — the supplier ``invoice_kwh`` and the effective
    kr/kWh (``invoice_total_nok / invoice_kwh``)."""
    tz = config.timezone
    to_month = periods.current_month(tz)
    from_month = periods.add_month(to_month, -(months - 1))
    window = periods.month_range(from_month, to_month)

    charging = ChargingRepo(db, tz=tz)
    posted = {
        s["period_month"]: s for s in SettlementRepo(db, tz=tz).list() if s["status"] == "posted"
    }

    def cost_per_kwh(row: dict[str, Any]) -> str | None:
        kwh, total = row.get("invoice_kwh"), row.get("invoice_total_nok")
        if kwh in (None, "") or total in (None, ""):
            return None
        divisor = Decimal(kwh)
        if divisor == 0:
            return None
        return str((Decimal(total) / divisor).quantize(Decimal("0.0001")))

    out: list[ChargingHistoryMonthOut] = []
    for month in window:
        assigned = sum(charging.consumption_by_member(month).values(), Decimal("0.00"))
        row = posted.get(month)
        out.append(
            ChargingHistoryMonthOut(
                month=month,
                assigned_kwh=str(assigned),
                unassigned_kwh=str(charging.unassigned_total_kwh(month)),
                grid_kwh=str(charging.total_kwh(month)),
                session_count=charging.session_count(month),
                invoice_kwh=(
                    str(row["invoice_kwh"])
                    if row is not None and row["invoice_kwh"] not in (None, "")
                    else None
                ),
                invoice_total_nok=(
                    str(row["invoice_total_nok"])
                    if row is not None and row["invoice_total_nok"] not in (None, "")
                    else None
                ),
                cost_per_kwh_nok=cost_per_kwh(row) if row is not None else None,
                settled=row is not None,
            )
        )
    return ChargingHistoryOut(months=out)


@router.get("/unassigned")
async def unassigned(
    month: str,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    repo = ChargingRepo(db, tz=config.timezone)
    _month_or_400(month)
    rows = repo.unassigned_consumption(month)
    return {
        "month": month,
        "chargers": [{**r, "energy_kwh": str(r["energy_kwh"])} for r in rows],
        "total_kwh": str(repo.unassigned_total_kwh(month)),
    }


@router.post("/reresolve", dependencies=[Depends(require_fetch)])
async def reresolve(
    month: str,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    repo = ChargingRepo(db, tz=config.timezone)
    return await repo.reresolve_members(_month_or_400(month), actor=actor)
