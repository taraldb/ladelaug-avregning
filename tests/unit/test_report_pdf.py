"""PDF settlement reports (Release 1C phase P4, decision C9, US-906).

WeasyPrint is an optional runtime dependency: its wheel installs anywhere but it
dlopen's Pango/cairo/GObject at import time, so on a host without those system
libraries ``PDF_AVAILABLE`` is ``False`` and the ``.pdf`` endpoints answer
``503 pdf_unavailable``. The rendering test is skipped in that case; the 503 and
RBAC tests run regardless.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.reports.pdf import PDF_AVAILABLE
from tests.conftest import MIGRATIONS_DIR

SYS = AuditContext.system()
MONTH = "2026-07"


def _build_posted_settlement(config, *, reference: str) -> tuple[int, int]:
    """Post a one-line settlement for a freshly created member on a throwaway
    connection (keeps the app's asyncio.Lock off this test's event loop).
    Returns ``(settlement_id, member_id)``."""
    sep = Database(config.database.path, migrations_dir=MIGRATIONS_DIR)

    async def _go() -> tuple[int, int]:
        state_dir = Path(config.database.path).parent
        repo = SettlementRepo(sep, state_dir=state_dir)
        members = MemberRepo(sep)
        mid = int(
            (
                await members.create(
                    member_reference=reference,
                    full_name="Ada Lovelace",
                    email=None,
                    join_date="2026-01-01",
                    actor=SYS,
                )
            )["id"]
        )
        await members.set_status(mid, "active", effective_from="2026-01-01", actor=SYS)
        sep.connection.execute(
            "INSERT INTO charging_sessions "
            "(zaptec_session_id, charger_zaptec_id, member_id, period_month, started_at, "
            " ended_at, energy_kwh, split_method, source, imported_at, updated_at) "
            "VALUES ('s1','z1',?,?, '2026-07-10T10:00:00+00:00','2026-07-10T12:00:00+00:00', "
            "'10','none','test','x','x')",
            (mid, MONTH),
        )
        sep.connection.commit()
        sid = int((await repo.create_draft(MONTH, actor=SYS))["id"])
        await repo.add_line(
            sid,
            description="Fastledd",
            allocation_method="equal",
            amount=Decimal(500),
            actor=SYS,
        )
        await repo.set_invoice(sid, invoice_kwh="10", actor=SYS)
        await repo.attach_invoice(sid, filename="f.pdf", content=b"%PDF", actor=SYS)
        await repo.freeze(sid, actor=SYS)
        await repo.post(sid, actor=SYS)
        return sid, mid

    try:
        return asyncio.run(_go())
    finally:
        sep.close()


@pytest.mark.skipif(not PDF_AVAILABLE, reason="WeasyPrint native libraries not installed")
def test_member_pdf_endpoint_renders(admin_client, config):
    sid, mid = _build_posted_settlement(config, reference="A-1")

    resp = admin_client.get(f"/api/settlement/{sid}/reports/{mid}.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")

    summary = admin_client.get(f"/api/settlement/{sid}/reports/summary.pdf")
    assert summary.status_code == 200
    assert summary.content.startswith(b"%PDF")


def test_pdf_unavailable_returns_503(admin_client, config, monkeypatch):
    monkeypatch.setattr("ladelaug_avregning.reports.pdf.PDF_AVAILABLE", False)
    sid, mid = _build_posted_settlement(config, reference="A-1")

    resp = admin_client.get(f"/api/settlement/{sid}/reports/{mid}.pdf")
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "pdf_unavailable"

    summary = admin_client.get(f"/api/settlement/{sid}/reports/summary.pdf")
    assert summary.status_code == 503
    assert summary.json()["detail"]["code"] == "pdf_unavailable"


def test_admin_pdf_routes_reject_member_session(member_client):
    assert member_client.get("/api/settlement/1/reports/1.pdf").status_code == 403
    assert member_client.get("/api/settlement/1/reports/summary.pdf").status_code == 403


def test_me_report_pdf_rejects_foreign_settlement(member_client, config):
    # member_client is member id 1 ("M-100"); this settlement is for someone else.
    sid, _ = _build_posted_settlement(config, reference="A-1")

    assert member_client.get("/api/me/settlements/999/report.pdf").status_code == 404
    foreign = member_client.get(f"/api/me/settlements/{sid}/report.pdf")
    assert foreign.status_code == 422
    assert foreign.json()["detail"]["code"] == "not_in_settlement"
