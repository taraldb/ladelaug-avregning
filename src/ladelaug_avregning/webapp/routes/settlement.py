"""Settlement endpoints (Epic 6).

``suggested-participants`` (US-203) plus the draft -> freeze -> preview -> post
engine. Router-level ``require_admin``; mutating routes add ``require_fetch``.
"""

from __future__ import annotations

import mimetypes
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from ladelaug_avregning import clock
from ladelaug_avregning.audit import AuditContext, record_audit
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.forecast import ForecastRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.errors import DomainError, NotFoundError
from ladelaug_avregning.reports import (
    html_to_pdf,
    render_member_report,
    render_summary_report,
)
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_db,
    require_admin,
    require_fetch,
)
from ladelaug_avregning.webapp.schemas import (
    InvoiceLineIn,
    InvoiceLinePatch,
    SettlementDraftIn,
    SettlementInvoiceIn,
    SuggestedParticipantOut,
)

router = APIRouter(
    prefix="/api/settlement", dependencies=[Depends(require_admin)], tags=["settlement"]
)


def _repo(db: Database, config: AppConfig) -> SettlementRepo:
    return SettlementRepo(db, tz=config.timezone)


def _pdf_response(html: str, filename: str) -> Response:
    """Render ``html`` to a PDF ``Response``. ``503 pdf_unavailable`` propagates
    from :func:`html_to_pdf` when WeasyPrint is not loadable on this host."""
    pdf = html_to_pdf(html)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


def _detail(repo: SettlementRepo, settlement_id: int) -> dict[str, Any]:
    row = repo.get(settlement_id)
    if row is None:
        raise NotFoundError(f"settlement {settlement_id} not found")
    detail = {
        "settlement": row,
        "lines": repo.lines(settlement_id),
        "snapshot": repo.snapshot_members(settlement_id),
        "attachments": repo.attachments(settlement_id),
        "corrections": repo.corrections(settlement_id),
    }
    if row["status"] == "posted":
        detail["correction_pending"] = repo.has_pending_correction(settlement_id)
    return detail


@router.get("/suggested-participants")
async def suggested_participants(
    on_date: str | None = None, db: Database = Depends(get_db)
) -> dict[str, Any]:
    resolved = on_date or clock.today_oslo().isoformat()
    rows = MemberRepo(db).suggested_participants(resolved)
    return {"on_date": resolved, "participants": [SuggestedParticipantOut(**r) for r in rows]}


@router.get("")
async def list_settlements(
    db: Database = Depends(get_db), config: AppConfig = Depends(get_config)
) -> dict[str, Any]:
    return {"settlements": _repo(db, config).list()}


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


@router.patch("/{settlement_id}/lines/{line_id}", dependencies=[Depends(require_fetch)])
async def update_line(
    settlement_id: int,
    line_id: int,
    body: InvoiceLinePatch,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    await _repo(db, config).update_line(
        settlement_id, line_id, actor=actor, **body.model_dump(exclude_unset=True)
    )
    return _detail(_repo(db, config), settlement_id)


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


@router.post(
    "/{settlement_id}/attachments",
    status_code=201,
    dependencies=[Depends(require_fetch)],
)
async def add_attachments(
    settlement_id: int,
    files: list[UploadFile] = File(...),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    repo = _repo(db, config)
    for file in files:
        await repo.add_attachment(
            settlement_id,
            filename=file.filename or "invoice.pdf",
            content=await file.read(),
            actor=actor,
        )
    return _detail(repo, settlement_id)


@router.get("/{settlement_id}/attachments/{attachment_id}")
async def download_attachment(
    settlement_id: int,
    attachment_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> FileResponse:
    repo = _repo(db, config)
    row = repo.attachment(settlement_id, attachment_id)
    path = repo.attachment_file(settlement_id, attachment_id)
    if row is None or path is None:
        raise NotFoundError(f"attachment {attachment_id} not found")
    await record_audit(
        db,
        actor,
        event_type="settlement.attachment_downloaded",
        entity_type="settlement",
        entity_id=settlement_id,
        summary=f"Attachment {row['filename']!r} downloaded from settlement {settlement_id}",
        detail={"attachment_id": attachment_id, "filename": row["filename"]},
    )
    media_type = mimetypes.guess_type(row["filename"])[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=row["filename"],
        content_disposition_type="inline",
    )


@router.delete(
    "/{settlement_id}/attachments/{attachment_id}",
    dependencies=[Depends(require_fetch)],
)
async def delete_attachment(
    settlement_id: int,
    attachment_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    repo = _repo(db, config)
    await repo.remove_attachment(settlement_id, attachment_id, actor=actor)
    return _detail(repo, settlement_id)


@router.post("/{settlement_id}/freeze", dependencies=[Depends(require_fetch)])
async def freeze(
    settlement_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    await _repo(db, config).freeze(settlement_id, actor=actor)
    return _detail(_repo(db, config), settlement_id)


@router.post("/{settlement_id}/share-draft", dependencies=[Depends(require_fetch)])
async def share_draft(
    settlement_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    """Publish a frozen draft to its members for preview (US-905). The member
    view of it is watermarked ``UTKAST``; 422 ``not_frozen`` for an unfrozen
    draft, 422 ``not_draft`` once posted."""
    await _repo(db, config).share_draft(settlement_id, actor=actor)
    return _detail(_repo(db, config), settlement_id)


@router.delete("/{settlement_id}/share-draft", dependencies=[Depends(require_fetch)])
async def unshare_draft(
    settlement_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    """Retract a shared draft (422 ``not_shared`` if it was not shared)."""
    await _repo(db, config).unshare_draft(settlement_id, actor=actor)
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


@router.post("/{settlement_id}/resend-reports", dependencies=[Depends(require_fetch)])
async def resend_reports(
    settlement_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    """Re-queue the per-member settlement report emails for a posted settlement
    (US-1001). Recomputes from the frozen snapshot and enqueues a fresh batch of
    ``email_messages`` rows — enqueue only, drained by ``/api/notifications/process``.
    422 ``not_posted`` for a draft."""
    repo = _repo(db, config)
    row = repo.get(settlement_id)
    if row is None:
        raise NotFoundError(f"settlement {settlement_id} not found")
    if row["status"] != "posted":
        raise DomainError("not_posted", "Only a posted settlement can re-send its reports.")
    result = repo.compute(settlement_id)
    queued = await NotificationRepo(db).enqueue_settlement_reports(
        settlement_id=settlement_id, result=result, base_url=config.email.base_url
    )
    await record_audit(
        db,
        actor,
        event_type="settlement.reports_resent",
        entity_type="settlement",
        entity_id=settlement_id,
        summary=f"Re-queued {queued} settlement report emails for {result['period_month']}",
        detail={"emails_queued": queued},
    )
    return {
        "settlement_id": settlement_id,
        "period_month": result["period_month"],
        "emails_queued": queued,
    }


@router.get("/{settlement_id}/correction")
async def assess_correction(
    settlement_id: int, db: Database = Depends(get_db), config: AppConfig = Depends(get_config)
) -> dict[str, Any]:
    """Recompute a posted settlement from current usage (US-701 / US-702). No writes."""
    return _repo(db, config).assess_correction(settlement_id)


@router.post("/{settlement_id}/correction", dependencies=[Depends(require_fetch)])
async def post_correction(
    settlement_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    """Book the assessed correction (US-703) and notify each adjusted member."""
    result = await _repo(db, config).post_correction(settlement_id, actor=actor)
    queued = await NotificationRepo(db).enqueue_correction_reports(
        settlement_id=settlement_id, correction=result, base_url=config.email.base_url
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


@router.get("/{settlement_id}/reports/summary.pdf")
async def summary_report_pdf(
    settlement_id: int, db: Database = Depends(get_db), config: AppConfig = Depends(get_config)
) -> Response:
    html = render_summary_report(_repo(db, config).compute(settlement_id))
    return _pdf_response(html, f"avregning-{settlement_id}-sammendrag.pdf")


@router.get("/{settlement_id}/reports/{member_id:int}", response_class=HTMLResponse)
async def member_report(
    settlement_id: int,
    member_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> HTMLResponse:
    repo = _repo(db, config)
    entry = repo.member_entry(settlement_id, member_id)
    if entry is None:
        raise DomainError("not_in_settlement", f"Member {member_id} is not in this settlement.")
    forecast = ForecastRepo(db).member_forecast(member_id)
    invoices = [
        {
            "filename": a["filename"],
            "href": f"/api/settlement/{settlement_id}/attachments/{a['id']}",
        }
        for a in repo.attachments(settlement_id)
    ]
    return HTMLResponse(
        render_member_report(entry["result"], entry["member"], forecast, invoices=invoices)
    )


@router.get("/{settlement_id}/reports/{member_id:int}.pdf")
async def member_report_pdf(
    settlement_id: int,
    member_id: int,
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> Response:
    entry = _repo(db, config).member_entry(settlement_id, member_id)
    if entry is None:
        raise DomainError("not_in_settlement", f"Member {member_id} is not in this settlement.")
    forecast = ForecastRepo(db).member_forecast(member_id)
    html = render_member_report(entry["result"], entry["member"], forecast)
    return _pdf_response(html, f"avregning-{settlement_id}-medlem-{member_id}.pdf")
