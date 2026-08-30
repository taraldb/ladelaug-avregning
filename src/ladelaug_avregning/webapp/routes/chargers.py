"""Admin charger management (Epic 3): records and effective-dated assignments.

Router-level ``require_admin`` gates the whole surface; mutating routes add
``require_fetch`` (CSRF). Zaptec sync of chargers lives in ``routes/zaptec.py``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.chargers import ChargerRepo
from ladelaug_avregning.domain.charging import ChargingRepo
from ladelaug_avregning.errors import NotFoundError
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_db,
    require_admin,
    require_fetch,
)
from ladelaug_avregning.webapp.schemas import (
    ChargerAssignIn,
    ChargerAssignmentOut,
    ChargerIn,
    ChargerOut,
    ChargerPatch,
    ChargerUnassignIn,
)

router = APIRouter(prefix="/api/chargers", dependencies=[Depends(require_admin)], tags=["chargers"])


def _require_charger(repo: ChargerRepo, charger_id: int) -> dict[str, Any]:
    row = repo.get(charger_id)
    if row is None:
        raise NotFoundError(f"charger {charger_id} not found")
    return row


@router.post("", status_code=201, dependencies=[Depends(require_fetch)])
async def create_charger(
    body: ChargerIn,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> ChargerOut:
    row = await ChargerRepo(db).create(
        name=body.name,
        serial_no=body.serial_no,
        zaptec_id=body.zaptec_id,
        device_type=body.device_type,
        actor=actor,
    )
    return ChargerOut.from_row(row)


@router.get("")
async def list_chargers(db: Database = Depends(get_db)) -> dict[str, list[ChargerOut]]:
    repo = ChargerRepo(db)
    assigned = repo.assignment_map()
    with_usage = repo.charger_ids_with_usage()
    return {
        "chargers": [
            ChargerOut.from_row(
                c,
                assigned_member_id=assigned.get(c["id"]),
                deletable=c["zaptec_id"] is None and c["id"] not in with_usage,
            )
            for c in repo.list()
        ]
    }


@router.get("/{charger_id}")
async def get_charger(charger_id: int, db: Database = Depends(get_db)) -> ChargerOut:
    repo = ChargerRepo(db)
    row = _require_charger(repo, charger_id)
    return ChargerOut.from_row(
        row,
        assigned_member_id=repo.assignment_on(charger_id),
        deletable=row["zaptec_id"] is None and not repo.has_usage(charger_id),
    )


@router.patch("/{charger_id}", dependencies=[Depends(require_fetch)])
async def update_charger(
    charger_id: int,
    body: ChargerPatch,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> ChargerOut:
    repo = ChargerRepo(db)
    row = await repo.update(charger_id, actor=actor, **body.model_dump(exclude_unset=True))
    return ChargerOut.from_row(
        row,
        assigned_member_id=repo.assignment_on(charger_id),
        deletable=row["zaptec_id"] is None and not repo.has_usage(charger_id),
    )


@router.delete("/{charger_id}", status_code=204, dependencies=[Depends(require_fetch)])
async def delete_charger(
    charger_id: int,
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> None:
    await ChargerRepo(db).delete(charger_id, actor=actor)


@router.post("/{charger_id}/assignments", dependencies=[Depends(require_fetch)])
async def assign_charger(
    charger_id: int,
    body: ChargerAssignIn,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, ChargerAssignmentOut]:
    row = await ChargerRepo(db).assign(
        charger_id,
        body.member_id,
        effective_from=body.effective_from,
        note=body.note,
        actor=actor,
    )
    await ChargingRepo(db, tz=config.timezone).reresolve_after_assignment(
        charger_id, since_month=row["effective_from"][:7], actor=actor
    )
    return {"assignment": ChargerAssignmentOut.from_row(row)}


@router.post("/{charger_id}/unassign", dependencies=[Depends(require_fetch)])
async def unassign_charger(
    charger_id: int,
    body: ChargerUnassignIn,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, ChargerAssignmentOut]:
    row = await ChargerRepo(db).unassign(charger_id, effective_to=body.effective_to, actor=actor)
    await ChargingRepo(db, tz=config.timezone).reresolve_after_assignment(
        charger_id, since_month=row["effective_from"][:7], actor=actor
    )
    return {"assignment": ChargerAssignmentOut.from_row(row)}


@router.get("/{charger_id}/assignments")
async def charger_assignments(
    charger_id: int, db: Database = Depends(get_db)
) -> dict[str, list[ChargerAssignmentOut]]:
    repo = ChargerRepo(db)
    _require_charger(repo, charger_id)
    return {"assignments": [ChargerAssignmentOut.from_row(r) for r in repo.assignments(charger_id)]}
