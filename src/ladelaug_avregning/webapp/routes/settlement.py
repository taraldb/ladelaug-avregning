"""Settlement endpoints (Epic 6).

``suggested-participants`` (US-203) plus the draft -> freeze -> preview -> post
engine. Router-level ``require_admin``; mutating routes add ``require_fetch``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import HTMLResponse

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.errors import DomainError, NotFoundError
from ladelaug_avregning.reports import render_member_report, render_summary_report
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_db,
    require_admin,
    require_fetch,
)
from ladelaug_avregning.webapp.schemas import (
    InvoiceLineIn,
    SettlementDraftIn,
    SettlementInvoiceIn,
    SuggestedParticipantOut,
)

router = APIRouter(
    prefix="/api/settlement", dependencies=[Depends(require_admin)], tags=["settlement"]
)


def _repo(db: Database, config: AppConfig) -> SettlementRepo:
    return SettlementRepo(db, tz=config.timezone)


def _detail(repo: SettlementRepo, settlement_id: int) -> dict[str, Any]:
    row = repo.get(settlement_id)
    if row is None:
        raise NotFoundError(f"settlement {settlement_id} not found")
    return {
        "settlement": row,
        "lines": repo.lines(settlement_id),
        "snapshot": repo.snapshot_members(settlement_id),
    }


@router.get("/suggested-participants")
async def suggested_participants(
    on_date: str | None = None, db: Database = Depends(get_db)
) -> dict[str, Any]:
    resolved = on_date or clock.today_oslo().isoformat()
    rows = MemberRepo(db).suggested_participants(resolved)
    return {"on_date": resolved, "participants": [SuggestedParticipantOut(**r) for r in rows]}


@router.get("")
async def list_settlements(db: Database = Depends(get_db)) -> dict[str, Any]:
    return {"settlements": SettlementRepo(db).list()}


@router.post("/drafts", status_code=201, dependencies=[Depends(require_fetch)])
async def create_draft(
    body: SettlementDraftIn,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    row = await _repo(db, config).create_draft(body.period_month, actor=actor)
    return {"settlement": row}


@router.get("/{settlement_id}")
async def get_settlement(
    settlement_id: int, db: Database = Depends(get_db), config: AppConfig = Depends(get_config)
) -> dict[str, Any]:
    return _detail(_repo(db, config), settlement_id)


@router.put("/{settlement_id}/invoice", dependencies=[Depends(require_fetch)])
async def set_invoice(
    settlement_id: int,
    body: SettlementInvoiceIn,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    await _repo(db, config).set_invoice(
        settlement_id, invoice_kwh=body.invoice_kwh, note=body.note, actor=actor
    )
    return _detail(_repo(db, config), settlement_id)


@router.post("/{settlement_id}/lines", status_code=201, dependencies=[Depends(require_fetch)])
async def add_line(
    settlement_id: int,
    body: InvoiceLineIn,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    line = await _repo(db, config).add_line(
        settlement_id,
        description=body.description,
        allocation_method=body.allocation_method,
        amount=body.amount,
        category=body.category,
        actor=actor,
    )
    return {"line": line}


@router.delete("/{settlement_id}/lines/{line_id}", dependencies=[Depends(require_fetch)])
async def delete_line(
    settlement_id: int,
    line_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    await _repo(db, config).delete_line(settlement_id, line_id, actor=actor)
    return _detail(_repo(db, config), settlement_id)


@router.post("/{settlement_id}/attachment", dependencies=[Depends(require_fetch)])
async def attach_invoice(
    settlement_id: int,
    file: UploadFile = File(...),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    content = await file.read()
    row = await _repo(db, config).attach_invoice(
        settlement_id,
        filename=file.filename or "invoice.pdf",
        content=content,
        actor=actor,
    )
    return {"settlement": row}


@router.post("/{settlement_id}/freeze", dependencies=[Depends(require_fetch)])
async def freeze(
    settlement_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    await _repo(db, config).freeze(settlement_id, actor=actor)
    return _detail(_repo(db, config), settlement_id)


@router.get("/{settlement_id}/preview")
async def preview(
    settlement_id: int, db: Database = Depends(get_db), config: AppConfig = Depends(get_config)
) -> dict[str, Any]:
    return _repo(db, config).preview(settlement_id)


@router.post("/{settlement_id}/post", dependencies=[Depends(require_fetch)])
async def post_settlement(
    settlement_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    result = await _repo(db, config).post(settlement_id, actor=actor)
    queued = await NotificationRepo(db).enqueue_settlement_reports(
        settlement_id=settlement_id, result=result, base_url=config.email.base_url
    )
    return {**result, "emails_queued": queued}


@router.get("/{settlement_id}/reports")
async def list_reports(
    settlement_id: int, db: Database = Depends(get_db), config: AppConfig = Depends(get_config)
) -> dict[str, Any]:
    repo = _repo(db, config)
    result = repo.compute(settlement_id)
    return {
        "settlement_id": settlement_id,
        "period_month": result["period_month"],
        "summary_url": f"/api/settlement/{settlement_id}/reports/summary",
        "members": [
            {
                "member_id": m["member_id"],
                "full_name": m["full_name"],
                "charge_nok": m["charge_nok"],
                "url": f"/api/settlement/{settlement_id}/reports/{m['member_id']}",
            }
            for m in result["members"]
        ],
    }


@router.get("/{settlement_id}/reports/summary", response_class=HTMLResponse)
async def summary_report(
    settlement_id: int, db: Database = Depends(get_db), config: AppConfig = Depends(get_config)
) -> HTMLResponse:
    return HTMLResponse(render_summary_report(_repo(db, config).compute(settlement_id)))


@router.get("/{settlement_id}/reports/{member_id}", response_class=HTMLResponse)
async def member_report(
    settlement_id: int,
    member_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> HTMLResponse:
    entry = _repo(db, config).member_entry(settlement_id, member_id)
    if entry is None:
        raise DomainError("not_in_settlement", f"Member {member_id} is not in this settlement.")
    return HTMLResponse(render_member_report(entry["result"], entry["member"]))
