"""Member self-service (US-104, member-facing US-501).

Everything here resolves the member id from the session via
``Depends(get_current_member)`` — never a path or query parameter — so a member
can only ever see their own record, balance, ledger, and status. A pure admin
(no linked member) gets 403; an anonymous caller gets 401.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response

from ladelaug_avregning.audit import AuditContext, record_audit
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain import periods
from ladelaug_avregning.domain.charging import ChargingRepo
from ladelaug_avregning.domain.forecast import ForecastRepo
from ladelaug_avregning.domain.ledger import LedgerRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.domain.sessions import SessionRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.domain.users import UserRepo
from ladelaug_avregning.errors import DomainError, NotFoundError
from ladelaug_avregning.money import nok_to_ore, ore_to_nok
from ladelaug_avregning.reports import html_to_pdf, render_member_report
from ladelaug_avregning.webapp.deps import (
    get_audit_context,
    get_config,
    get_current_member,
    get_current_user,
    get_db,
    require_fetch,
)
from ladelaug_avregning.webapp.schemas import (
    LedgerTxnOut,
    MemberConsumptionOut,
    MemberForecastOut,
    MemberHistoryMonthOut,
    MemberHistoryOut,
    MemberOut,
    MePasswordIn,
    MeProfileIn,
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


@router.patch("", dependencies=[Depends(require_fetch)])
async def update_me(
    body: MeProfileIn,
    member_id: int = Depends(get_current_member),
    db: Database = Depends(get_db),
    actor: AuditContext = Depends(get_audit_context),
) -> MemberOut:
    """Let a member edit their own name / contact email (US-104). Same
    ``MemberRepo.update`` + ``member.updated`` audit the admin PATCH uses;
    ``member_reference`` / ``join_date`` are not accepted here."""
    repo = MemberRepo(db)
    row = await repo.update(member_id, actor=actor, **body.model_dump(exclude_unset=True))
    return MemberOut.from_row(
        row,
        status=repo.current_status(member_id),
        participates=repo.effective_participation(member_id),
    )


@router.post("/password", dependencies=[Depends(require_fetch)])
async def change_my_password(
    body: MePasswordIn,
    request: Request,
    member_id: int = Depends(get_current_member),
    user: dict[str, Any] = Depends(get_current_user),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> dict[str, Any]:
    """Set a new password for the caller's own login. No current-password check
    (the live session is the proof of identity); every *other* session is
    revoked and a heads-up email is queued."""
    auth = config.auth
    argon2 = (auth.argon2_time_cost, auth.argon2_memory_cost_kib, auth.argon2_parallelism)
    user_id = int(user["id"])
    await UserRepo(db).set_password(user_id, body.new_password, actor=actor, argon2=argon2)

    token = request.cookies.get(auth.cookie_name)
    if token:
        await SessionRepo(db).revoke_all_for_user_except(user_id, token)

    await record_audit(
        db,
        actor,
        event_type="auth.password_changed",
        entity_type="user",
        entity_id=user_id,
        summary=f"{user['email']} changed their own password; other sessions revoked",
    )
    if user["email"]:
        await NotificationRepo(db).enqueue(
            to_address=user["email"],
            subject="Passordet ditt ble endret",
            body_text=(
                "Passordet til ladelaug-kontoen din ble nettopp endret. "
                "Var det ikke deg, kontakt styret straks."
            ),
            template="password_changed",
            related_entity_type="user",
            related_entity_id=user_id,
        )
    return {"ok": True}


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


@router.get("/access")
async def my_access(
    member_id: int = Depends(get_current_member),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, Any]:
    """Charging-access status for the portal banner (US-305). ``portal_url`` is
    where the member goes if their access has been warned/disabled."""
    from ladelaug_avregning.domain.access import AccessRepo

    return {
        "status": AccessRepo(db).current(member_id),
        "portal_url": config.zaptec.portal_url,
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


@router.get("/history")
async def my_history(
    member_id: int = Depends(get_current_member),
    months: int = Query(default=6, ge=1, le=24),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> MemberHistoryOut:
    """Rolling per-month strip for the member dashboard: metered kWh + session
    count for every month (works before a settlement exists), the kr charge for
    months whose settlement is posted, and the running ledger balance at each
    month's end."""
    tz = config.timezone
    to_month = periods.current_month(tz)
    from_month = periods.add_month(to_month, -(months - 1))
    window = periods.month_range(from_month, to_month)

    charging = ChargingRepo(db, tz=tz)
    settlements = SettlementRepo(db, tz=tz)
    posted = {s["period_month"]: s for s in settlements.posted_for_member(member_id)}

    running = LedgerRepo(db).running_balance_by_month(member_id)

    def balance_end_ore(month: str) -> int:
        value = 0
        for ym, bal in running:
            if ym <= month:
                value = bal
            else:
                break
        return value

    out: list[MemberHistoryMonthOut] = []
    for month in window:
        charge_nok: str | None = None
        charge_ore: int | None = None
        settled = False
        row = posted.get(month)
        if row is not None:
            entry = settlements.member_entry(int(row["id"]), member_id)
            if entry is not None:
                charge_nok = entry["member"]["charge_nok"]
                charge_ore = nok_to_ore(Decimal(charge_nok))
                settled = True
        bal = balance_end_ore(month)
        out.append(
            MemberHistoryMonthOut(
                month=month,
                consumption_kwh=str(charging.member_consumption(member_id, month)),
                session_count=charging.member_session_count(member_id, month),
                charge_nok=charge_nok,
                charge_ore=charge_ore,
                settled=settled,
                balance_end_nok=str(ore_to_nok(bal)),
                balance_end_ore=bal,
            )
        )
    return MemberHistoryOut(months=out)


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


def _my_settlement_or_403(
    repo: SettlementRepo, settlement_id: int, member_id: int
) -> dict[str, Any]:
    row = repo.get(settlement_id)
    if row is None or row["status"] != "posted":
        raise NotFoundError(f"settlement {settlement_id} not found")
    if settlement_id not in {s["id"] for s in repo.posted_for_member(member_id)}:
        raise DomainError("not_in_settlement", "You are not part of this settlement.")
    return row


def _my_report_html(settlement_id: int, member_id: int, db: Database, config: AppConfig) -> str:
    repo = SettlementRepo(db, tz=config.timezone)
    _my_settlement_or_403(repo, settlement_id, member_id)
    entry = repo.member_entry(settlement_id, member_id)
    if entry is None:
        raise DomainError("not_in_settlement", "You are not part of this settlement.")
    forecast = ForecastRepo(db).member_forecast(member_id)
    # Relative to /api/me/settlements/{id}/report[.pdf] -> .../invoices/{aid}
    invoices = [
        {"filename": a["filename"], "href": f"invoices/{a['id']}"}
        for a in repo.attachments(settlement_id)
    ]
    return render_member_report(entry["result"], entry["member"], forecast, invoices=invoices)


@router.get("/settlements/{settlement_id}/invoices/{attachment_id}")
async def my_settlement_invoice(
    settlement_id: int,
    attachment_id: int,
    member_id: int = Depends(get_current_member),
    db: Database = Depends(get_db),
    config: AppConfig = Depends(get_config),
    actor: AuditContext = Depends(get_audit_context),
) -> FileResponse:
    repo = SettlementRepo(db, tz=config.timezone)
    _my_settlement_or_403(repo, settlement_id, member_id)
    row = repo.attachment(settlement_id, attachment_id)
    path = repo.attachment_file(settlement_id, attachment_id)
    if row is None or path is None:
        raise NotFoundError(f"attachment {attachment_id} not found")
    await record_audit(
        db,
        actor,
        event_type="settlement.invoice_downloaded",
        entity_type="settlement",
        entity_id=settlement_id,
        summary=f"Member downloaded invoice {row['filename']!r} for settlement {settlement_id}",
        detail={"member_id": member_id, "attachment_id": attachment_id},
    )
    return FileResponse(path, media_type="application/pdf", filename=row["filename"])


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
    actor: AuditContext = Depends(get_audit_context),
) -> Response:
    html = _my_report_html(settlement_id, member_id, db, config)
    await record_audit(
        db,
        actor,
        event_type="settlement.report_downloaded",
        entity_type="settlement",
        entity_id=settlement_id,
        summary=f"Member downloaded the PDF report for settlement {settlement_id}",
        detail={"member_id": member_id},
    )
    return Response(
        content=html_to_pdf(html),
        media_type="application/pdf",
        headers={"Content-Disposition": (f'inline; filename="avregning-{settlement_id}.pdf"')},
    )
