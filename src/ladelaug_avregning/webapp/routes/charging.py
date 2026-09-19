"""Admin views over imported charging data (Epic 4 / US-304).

``consumption`` and ``unassigned`` feed the settlement freeze step; ``reresolve``
recomputes member attribution after an assignment gap is filled.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain import periods
from ladelaug_avregning.domain.charging import ChargingRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.errors import DomainError, NotFoundError
from ladelaug_avregning.money import ore_to_nok
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_db,
    require_admin,
    require_fetch,
)
from ladelaug_avregning.webapp.schemas import (
    ChargingHistoryMonthOut,
    ChargingHistoryOut,
    TopHoursOut,
    UsageOut,
)

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


@router.get("/sessions/{zaptec_session_id}")
async def session_detail(
    zaptec_session_id: str,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    """One charging session in full: its per-month parts + the 15-minute interval
    energy points imported for it. Drives the "Ladeøkter" row drill-down."""
    detail = ChargingRepo(db, tz=config.timezone).session_detail(zaptec_session_id)
    if detail is None:
        raise NotFoundError("charging session not found")
    return detail


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
    settlement is posted — the supplier ``invoice_kwh``, the effective kr/kWh
    (``invoice_total_nok / invoice_kwh``), and the invoiced cost split into
    ``consumption``-allocated vs ``equal``-allocated (fixed) totals."""
    tz = config.timezone
    to_month = periods.current_month(tz)
    from_month = periods.add_month(to_month, -(months - 1))
    window = periods.month_range(from_month, to_month)

    charging = ChargingRepo(db, tz=tz)
    settlements = SettlementRepo(db, tz=tz)
    posted = {s["period_month"]: s for s in settlements.list() if s["status"] == "posted"}

    def cost_per_kwh(row: dict[str, Any]) -> str | None:
        kwh, total = row.get("invoice_kwh"), row.get("invoice_total_nok")
        if kwh in (None, "") or total in (None, ""):
            return None
        divisor = Decimal(kwh)
        if divisor == 0:
            return None
        return str((Decimal(total) / divisor).quantize(Decimal("0.0001")))

    def cost_split(row: dict[str, Any]) -> tuple[str | None, str | None]:
        """Split a posted settlement's invoice lines into ``consumption``-allocated
        (forbrukskostnader) vs ``equal``-allocated (faste kostnader) totals.
        ``(None, None)`` when the settlement carries no itemised lines."""
        lines = settlements.lines(row["id"])
        if not lines:
            return None, None
        consumption = sum(
            int(ln["amount_ore"]) for ln in lines if ln["allocation_method"] == "consumption"
        )
        fixed = sum(int(ln["amount_ore"]) for ln in lines if ln["allocation_method"] == "equal")
        return str(ore_to_nok(consumption)), str(ore_to_nok(fixed))

    out: list[ChargingHistoryMonthOut] = []
    for month in window:
        assigned = sum(charging.consumption_by_member(month).values(), Decimal("0.00"))
        row = posted.get(month)
        consumption_cost_nok, fixed_cost_nok = cost_split(row) if row is not None else (None, None)
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
                consumption_cost_nok=consumption_cost_nok,
                fixed_cost_nok=fixed_cost_nok,
                settled=row is not None,
            )
        )
    return ChargingHistoryOut(months=out)


def _end_or_400(end: str) -> str:
    try:
        datetime.fromisoformat(end.strip())
    except ValueError as exc:
        raise DomainError("bad_end", "end must be an ISO-8601 datetime") from exc
    return end


@router.get("/usage")
async def usage(
    hours: int = Query(default=168, ge=1, le=720),
    end: str | None = None,
    month: str | None = None,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> UsageOut:
    """Hourly usage for the admin "Bruk" chart: average power delivered and
    active-charging vs. plugged-in-idle session counts. Either the trailing
    ``hours`` (default: ending now) or, when ``month`` is given, one full local
    calendar month — ``month`` wins if both are present. ``end`` pages the
    trailing window back through history — pass an earlier ``hour`` value from
    a previous response to shift the window; ignored when ``month`` is set."""
    repo = ChargingRepo(db, tz=config.timezone)
    if month is not None:
        return UsageOut(hours=repo.usage_for_month(_month_or_400(month)))
    return UsageOut(
        hours=repo.usage_timeseries(hours=hours, end=_end_or_400(end) if end is not None else None)
    )


@router.get("/peak-hours")
async def peak_hours(
    month: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> TopHoursOut:
    """The busiest ``limit`` hours in one local calendar month (default: the
    current month) for the admin "Bruk" page's top-hours list."""
    tz = config.timezone
    m = _month_or_400(month) if month is not None else periods.current_month(tz)
    repo = ChargingRepo(db, tz=tz)
    return TopHoursOut(month=m, hours=repo.top_hours(m, limit=limit))


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
