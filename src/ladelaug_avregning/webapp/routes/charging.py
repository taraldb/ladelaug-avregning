"""Admin views over imported charging data (Epic 4 / US-304).

``consumption`` and ``unassigned`` feed the settlement freeze step; ``reresolve``
recomputes member attribution after an assignment gap is filled.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain import periods
from ladelaug_avregning.domain.charging import ChargingRepo
from ladelaug_avregning.errors import DomainError
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_db,
    require_admin,
    require_fetch,
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
