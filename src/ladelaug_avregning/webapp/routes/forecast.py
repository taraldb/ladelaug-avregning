"""Admin forecast settings + member-forecast overview (Epic 8).

Router-level ``require_admin``; the mutating ``PUT`` adds ``require_fetch``. The
audit row for a settings change is written by ``ForecastRepo.update_settings``
inside its own locked transaction.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.forecast import ForecastRepo
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_db,
    require_admin,
    require_fetch,
)
from ladelaug_avregning.webapp.schemas import ForecastSettingsIn, ForecastSettingsOut

router = APIRouter(prefix="/api/forecast", dependencies=[Depends(require_admin)], tags=["forecast"])


@router.get("/settings")
async def get_settings(db: Database = Depends(get_db)) -> ForecastSettingsOut:
    return ForecastSettingsOut.from_row(ForecastRepo(db).settings())


@router.put("/settings", dependencies=[Depends(require_fetch)])
async def update_settings(
    body: ForecastSettingsIn,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> ForecastSettingsOut:
    updated = await ForecastRepo(db).update_settings(actor=actor, **body.to_update_kwargs())
    return ForecastSettingsOut.from_row(updated)


@router.get("/members")
async def member_forecasts(db: Database = Depends(get_db)) -> dict[str, Any]:
    return {"members": ForecastRepo(db).all_member_forecasts()}
