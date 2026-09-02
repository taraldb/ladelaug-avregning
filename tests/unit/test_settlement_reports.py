from __future__ import annotations

from decimal import Decimal

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.domain.settlement import SettlementRepo
from ladelaug_avregning.errors import DomainError
from ladelaug_avregning.reports import render_member_report, render_summary_report
from ladelaug_avregning.reports.settlement_report import _nok

FETCH = {"X-Requested-With": "fetch"}
MONTH = "2026-07"
# nb-NO uses a non-breaking space as the thousands separator and after the "kr" prefix.
NBSP = " "


def _money(number: str) -> str:
    """The ``<span class="money">`` markup ``_nok`` wraps an amount in; ``number``
    is the nb-NO digit string (NBSP-grouped, decimal comma)."""
    return (
        f'<span class="money"><span class="cur">kr</span><span class="amt">{number}</span></span>'
    )


def test_nok_formats_norwegian():
    assert _nok("1234.5") == _money(f"1{NBSP}234,50")
    assert _nok("-50") == _money("-50,00")
    assert _nok("1000000") == _money(f"1{NBSP}000{NBSP}000,00")


def _result_and_member():
    member = {
        "member_id": 1,
        "member_reference": "A-07",
        "full_name": "Kari Nordmann",
        "is_active": True,
        "participates_equal": True,
        "consumption_kwh": "12.5",
        "session_count": 4,
        "balance_before_ore": 150000,
        "balance_before_nok": "1500.00",
        "charge_ore": 45000,
        "charge_nok": "450.00",
        "balance_after_ore": 105000,
        "balance_after_nok": "1050.00",
        "lines": [
            {
                "invoice_line_id": 1,
                "description": "Fastledd",
                "kind": "equal",
                "amount_ore": 30000,
                "amount_nok": "300.00",
            },
            {
                "invoice_line_id": 2,
                "description": "Energi",
                "kind": "consumption",
                "amount_ore": 15000,
                "amount_nok": "150.00",
            },
        ],
    }
    other = {
        "member_id": 2,
        "member_reference": "A-08",
        "full_name": "Ola Nordmann",
        "is_active": True,
        "participates_equal": True,
        "consumption_kwh": "37.5",
        "session_count": 9,
        "balance_before_ore": 200000,
        "balance_before_nok": "2000.00",
        "charge_ore": 75000,
        "charge_nok": "750.00",
        "balance_after_ore": 125000,
        "balance_after_nok": "1250.00",
        "lines": [],
    }
    result = {
        "period_month": MONTH,
        "status": "posted",
        "invoice_kwh": "40",
        "grid_kwh": "38.2",
        "invoice_lines_total_ore": 120000,
        "invoice_lines_total_nok": "1200.00",
        "total_charged_ore": 120000,
        "total_charged_nok": "1200.00",
        "members": [member, other],
        "lines": [
            {
                "line_id": 1,
                "description": "Fastledd",
                "kind": "equal",
                "amount_ore": 60000,
                "allocated_ore": 60000,
                "recipients": 2,
            },
            {
                "line_id": 2,
                "description": "Energi",
                "kind": "consumption",
                "amount_ore": 60000,
                "allocated_ore": 60000,
                "recipients": 2,
            },
        ],
        "warnings": [],
    }
    return result, member


_PLACEHOLDER = "Prognose og anbefalt innbetaling kommer i en senere versjon"


def _available_forecast():
    return {
        "member_id": 1,
        "available": True,
        "forecast_kwh": "13.333333333333333333333333333",
        "rate_ore_per_kwh": "250",
        "rate_source": "derived",
        "equal_share_ore": 20000,
        "forecast_monthly_cost_ore": 53333,
        "recommended_minimum_ore": 106666,
        "balance_ore": 40000,
        "recommended_topup_ore": 66666,
        "low_balance": True,
        "severity": "critical",
        "reason": None,
    }


def test_render_member_report_contains_key_figures():
    result, member = _result_and_member()
    page = render_member_report(result, member)
    assert "Avregning 2026-07" in page
    assert "Kari Nordmann" in page
    assert "A-07" in page
    assert "12,5 kWh" in page
    assert _money("450,00") in page
    assert _money(f"1{NBSP}050,00") in page  # balance after
    assert "<!doctype html>" in page
    # The 1B stub is gone; with no forecast a neutral footer stands in.
    assert _PLACEHOLDER not in page
    assert "Prognose neste måned" not in page
    assert "ikke tilgjengelig" in page


def test_render_member_report_shows_settlement_calculation():
    result, member = _result_and_member()
    page = render_member_report(result, member)
    assert "Avregningsgrunnlag" in page
    assert _money(f"1{NBSP}200,00") in page  # Sum fakturagrunnlag + total charged
    # the fixed/consumption split is no longer summarised in Avregningsgrunnlag;
    # it is itemised per line in Kostnadsfordeling instead
    assert "Faste kostnader (delt likt)" not in page
    assert "Forbrukskostnader (etter kWh)" not in page
    assert _money("600,00") in page  # "Fastledd" line total (60000 øre) in the table
    # my share of the metered energy: 12.5 of 50 kWh
    assert "Din andel av totalforbruk" in page
    assert "12,5 av 50 kWh (25,0 %)" in page
    # per-line table gains a settlement-wide total column
    assert "Totalbeløp" in page
    assert "Faktura fra strømleverandør" not in page  # no invoice_href passed


def test_render_member_report_invoice_link_when_available():
    result, member = _result_and_member()
    page = render_member_report(
        result,
        member,
        invoices=[
            {"filename": "faktura-a.pdf", "href": "invoices/5"},
            {"filename": "faktura-b.pdf", "href": "invoices/6"},
        ],
    )
    assert "Faktura fra strømleverandør" in page
    assert 'href="invoices/5"' in page
    assert "faktura-a.pdf" in page
    assert "faktura-b.pdf" in page


def test_render_member_report_forecast_section():
    result, member = _result_and_member()
    page = render_member_report(result, member, _available_forecast())
    assert _PLACEHOLDER not in page
    assert "Prognose neste måned" in page
    assert "13.33 kWh" in page  # forecast kWh, quantised
    assert "Anbefalt saldo / innbetaling" in page
    assert _money(f"1{NBSP}066,66") in page  # recommended minimum balance
    assert "Anbefalt innbetaling for å nå anbefalt saldo" in page
    assert _money("666,66") in page  # recommended top-up


def test_render_member_report_forecast_unavailable_is_neutral():
    result, member = _result_and_member()
    fc = {**_available_forecast(), "available": False, "reason": "insufficient_history"}
    page = render_member_report(result, member, fc)
    assert _PLACEHOLDER not in page
    assert "Prognose neste måned" not in page
    assert "ikke tilgjengelig" in page


def test_render_summary_lists_members_and_warnings():
    result, _ = _result_and_member()
    result["warnings"] = [{"code": "negative_balances", "member_ids": [1]}]
    page = render_summary_report(result)
    assert "sammendrag" in page
    assert "Kari Nordmann" in page
    assert "Ola Nordmann" in page
    assert "negative_balances" in page
    assert "Faste kostnader (delt likt)" in page
    assert "Forbrukskostnader (etter kWh)" in page


async def _posted(db, state_dir=None):
    repo = SettlementRepo(db, state_dir=state_dir)
    m1 = int(
        (
            await MemberRepo(db).create(
                member_reference="A-1",
                full_name="Ada",
                email=None,
                join_date="2026-01-01",
                actor=AuditContext.system(),
            )
        )["id"]
    )
    await MemberRepo(db).set_status(
        m1, "active", effective_from="2026-01-01", actor=AuditContext.system()
    )
    db.connection.execute(
        "INSERT INTO charging_sessions "
        "(zaptec_session_id, charger_zaptec_id, member_id, period_month, started_at, ended_at, "
        " energy_kwh, split_method, source, imported_at, updated_at) "
        "VALUES ('s1','z1',?,?, '2026-07-10T10:00:00+00:00','2026-07-10T12:00:00+00:00', "
        "'10','none','test','x','x')",
        (m1, MONTH),
    )
    db.connection.commit()
    s = await repo.create_draft(MONTH, actor=AuditContext.system())
    sid = int(s["id"])
    await repo.add_line(
        sid,
        description="Fastledd",
        allocation_method="equal",
        amount=Decimal(500),
        actor=AuditContext.system(),
    )
    await repo.set_invoice(sid, invoice_kwh="10", actor=AuditContext.system())
    await repo.add_attachment(sid, filename="f.pdf", content=b"%PDF", actor=AuditContext.system())
    await repo.freeze(sid, actor=AuditContext.system())
    await repo.post(sid, actor=AuditContext.system())
    return repo, sid, m1


async def test_write_reports_persists_files_on_post(db, tmp_path):
    _, _, m1 = await _posted(db, state_dir=tmp_path)
    report_dir = tmp_path / "reports" / MONTH
    assert (report_dir / "sammendrag.html").is_file()
    assert (report_dir / f"medlem-{m1}.html").is_file()
    assert "Ada" in (report_dir / f"medlem-{m1}.html").read_text(encoding="utf-8")


async def test_regenerate_reports_rewrites_stale_files(db, tmp_path):
    repo, sid, m1 = await _posted(db, state_dir=tmp_path)
    member_file = tmp_path / "reports" / MONTH / f"medlem-{m1}.html"
    member_file.write_text("STALE", encoding="utf-8")

    out = repo.regenerate_reports(sid)

    assert out["settlement_id"] == sid
    assert out["period_month"] == MONTH
    assert f"medlem-{m1}.html" in out["files"] and "sammendrag.html" in out["files"]
    fresh = member_file.read_text(encoding="utf-8")
    assert "STALE" not in fresh
    assert 'class="money"' in fresh and "Ada" in fresh


async def test_regenerate_reports_rejects_draft(db, tmp_path):
    repo = SettlementRepo(db, state_dir=tmp_path)
    draft = await repo.create_draft("2026-09", actor=AuditContext.system())
    with pytest.raises(DomainError) as exc:
        repo.regenerate_reports(int(draft["id"]))
    assert exc.value.code == "not_posted"


# --- routes ------------------------------------------------------------


def _build_frozen_settlement(admin_client, m1):
    db = admin_client.app.state.db
    db.connection.execute(
        "INSERT INTO charging_sessions "
        "(zaptec_session_id, charger_zaptec_id, member_id, period_month, started_at, ended_at, "
        " energy_kwh, split_method, source, imported_at, updated_at) "
        "VALUES ('s1','z1',?,?, '2026-07-10T10:00:00+00:00','2026-07-10T12:00:00+00:00', "
        "'10','none','test','x','x')",
        (m1, MONTH),
    )
    db.connection.commit()
    sid = admin_client.post(
        "/api/settlement/drafts", json={"period_month": MONTH}, headers=FETCH
    ).json()["settlement"]["id"]
    admin_client.post(
        f"/api/settlement/{sid}/lines",
        json={"description": "Fastledd", "allocation_method": "equal", "amount": "500"},
        headers=FETCH,
    )
    admin_client.put(f"/api/settlement/{sid}/invoice", json={"invoice_kwh": "10"}, headers=FETCH)
    admin_client.post(
        f"/api/settlement/{sid}/attachments",
        files={"files": ("f.pdf", b"%PDF", "application/pdf")},
        headers=FETCH,
    )
    admin_client.post(f"/api/settlement/{sid}/freeze", headers=FETCH)
    return sid


def test_report_routes_over_http(admin_client, make_member):
    m1 = make_member(member_reference="A-1")
    admin_client.post(
        f"/api/members/{m1}/status",
        json={"status": "active", "effective_from": "2026-01-01"},
        headers=FETCH,
    )
    sid = _build_frozen_settlement(admin_client, m1)

    listing = admin_client.get(f"/api/settlement/{sid}/reports").json()
    assert listing["members"][0]["member_id"] == m1

    summary = admin_client.get(f"/api/settlement/{sid}/reports/summary")
    assert summary.status_code == 200 and "text/html" in summary.headers["content-type"]
    member_html = admin_client.get(f"/api/settlement/{sid}/reports/{m1}")
    assert member_html.status_code == 200 and "Avregning 2026-07" in member_html.text
    assert admin_client.get(f"/api/settlement/{sid}/reports/9999").status_code == 422

    # the settlement is frozen but NOT posted — the PDF routes must still render
    # (200) rather than gate on posted; 503 only if WeasyPrint is unavailable.
    assert admin_client.get(f"/api/settlement/{sid}").json()["settlement"]["status"] == "draft"
    for url in (
        f"/api/settlement/{sid}/reports/summary.pdf",
        f"/api/settlement/{sid}/reports/{m1}.pdf",
    ):
        assert admin_client.get(url).status_code in (200, 503)


def test_me_settlements_scoped_and_empty_by_default(member_client):
    assert member_client.get("/api/me/settlements").json() == {"settlements": []}
    assert member_client.get("/api/me/settlements/999/report").status_code == 404


def test_admin_can_download_invoice_attachment(admin_client, make_member):
    m1 = make_member(member_reference="A-1")
    admin_client.post(
        f"/api/members/{m1}/status",
        json={"status": "active", "effective_from": "2026-01-01"},
        headers=FETCH,
    )
    sid = _build_frozen_settlement(admin_client, m1)

    detail = admin_client.get(f"/api/settlement/{sid}").json()
    assert len(detail["attachments"]) == 1
    aid = detail["attachments"][0]["id"]
    assert detail["attachments"][0]["filename"] == "f.pdf"

    resp = admin_client.get(f"/api/settlement/{sid}/attachments/{aid}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF"

    # a second invoice can be added even after freezing
    detail = admin_client.post(
        f"/api/settlement/{sid}/attachments",
        files={"files": ("faktura-2.pdf", b"%PDF two", "application/pdf")},
        headers=FETCH,
    ).json()
    assert len(detail["attachments"]) == 2

    # member report lists every invoice, linking to the settlement-scoped route
    aid2 = detail["attachments"][1]["id"]
    member_html = admin_client.get(f"/api/settlement/{sid}/reports/{m1}").text
    assert "Avregningsgrunnlag" in member_html
    assert "Faktura fra strømleverandør" in member_html
    assert "faktura-2.pdf" in member_html
    assert f'href="/api/settlement/{sid}/attachments/{aid2}"' in member_html
    assert "../../attachments/" not in member_html

    # delete one; the settlement (still a draft here) keeps the other
    deleted = admin_client.delete(f"/api/settlement/{sid}/attachments/{aid}", headers=FETCH)
    assert deleted.status_code == 200
    assert [a["filename"] for a in deleted.json()["attachments"]] == ["faktura-2.pdf"]
    assert admin_client.get(f"/api/settlement/{sid}/attachments/{aid}").status_code == 404


def test_member_sees_calculation_and_invoice(
    admin_client, config, make_member, seed_user_sync, make_session
):
    from fastapi.testclient import TestClient

    m1 = make_member(member_reference="A-1", email="ada@example.com")
    admin_client.post(
        f"/api/members/{m1}/status",
        json={"status": "active", "effective_from": "2026-01-01"},
        headers=FETCH,
    )
    sid = _build_frozen_settlement(admin_client, m1)
    assert admin_client.post(f"/api/settlement/{sid}/post", headers=FETCH).status_code == 200
    aid = admin_client.get(f"/api/settlement/{sid}").json()["attachments"][0]["id"]

    uid = seed_user_sync(email="ada@example.com", role="member", member_id=m1)
    with TestClient(admin_client.app) as me:
        me.cookies.set(config.auth.cookie_name, make_session(uid))

        listing = me.get("/api/me/settlements").json()["settlements"]
        assert len(listing) == 1
        # the invoice is reachable only through the report, not the settlement list
        assert "invoices" not in listing[0]

        report = me.get(f"/api/me/settlements/{sid}/report")
        assert report.status_code == 200
        assert "Avregningsgrunnlag" in report.text
        assert "Din andel av totalforbruk" in report.text
        assert "Faktura fra strømleverandør" in report.text
        assert f"invoices/{aid}" in report.text

        invoice = me.get(f"/api/me/settlements/{sid}/invoices/{aid}")
        assert invoice.status_code == 200
        assert invoice.content == b"%PDF"

    # a member not in the settlement is refused
    other = make_member(member_reference="B-2", email="bob@example.com")
    other_uid = seed_user_sync(email="bob@example.com", role="member", member_id=other)
    with TestClient(admin_client.app) as bob:
        bob.cookies.set(config.auth.cookie_name, make_session(other_uid))
        assert bob.get(f"/api/me/settlements/{sid}/invoices/{aid}").status_code == 422


def test_member_sees_shared_draft_watermarked_but_not_before_sharing(
    admin_client, config, make_member, seed_user_sync, make_session
):
    """A frozen draft is invisible to members until the board shares it; once
    shared, the member's report is clearly marked UTKAST and the listing flags
    it as a draft. Retracting hides it again."""
    from fastapi.testclient import TestClient

    m1 = make_member(member_reference="A-1", email="ada@example.com")
    admin_client.post(
        f"/api/members/{m1}/status",
        json={"status": "active", "effective_from": "2026-01-01"},
        headers=FETCH,
    )
    sid = _build_frozen_settlement(admin_client, m1)  # frozen, still a draft

    uid = seed_user_sync(email="ada@example.com", role="member", member_id=m1)
    with TestClient(admin_client.app) as me:
        me.cookies.set(config.auth.cookie_name, make_session(uid))

        # not shared yet -> nothing visible
        assert me.get("/api/me/settlements").json() == {"settlements": []}
        assert me.get(f"/api/me/settlements/{sid}/report").status_code == 404

        # board shares the draft
        shared = admin_client.post(f"/api/settlement/{sid}/share-draft", headers=FETCH)
        assert shared.status_code == 200
        assert shared.json()["settlement"]["draft_shared_at"] is not None

        listing = me.get("/api/me/settlements").json()["settlements"]
        assert len(listing) == 1
        assert listing[0]["is_draft"] is True
        assert listing[0]["posted_at"] is None

        report = me.get(f"/api/me/settlements/{sid}/report")
        assert report.status_code == 200
        # a diagonal watermark, but no banner/heading marker in the report body
        assert '<div class="draft-watermark">UTKAST</div>' in report.text
        assert "Avregning 2026-07" in report.text and "(UTKAST)" not in report.text
        # the real calculation is still shown
        assert "Din andel av totalforbruk" in report.text

        pdf = me.get(f"/api/me/settlements/{sid}/report.pdf")
        assert pdf.status_code in (200, 503)

        # board retracts -> hidden again
        assert (
            admin_client.request(
                "DELETE", f"/api/settlement/{sid}/share-draft", headers=FETCH
            ).status_code
            == 200
        )
        assert me.get("/api/me/settlements").json() == {"settlements": []}
        assert me.get(f"/api/me/settlements/{sid}/report").status_code == 404


def test_share_draft_requires_frozen_draft(admin_client, make_member):
    m1 = make_member(member_reference="A-1")
    admin_client.post(
        f"/api/members/{m1}/status",
        json={"status": "active", "effective_from": "2026-01-01"},
        headers=FETCH,
    )

    # an unfrozen draft (distinct month) cannot be shared, nor unshared
    sid = admin_client.post(
        "/api/settlement/drafts", json={"period_month": "2026-09"}, headers=FETCH
    ).json()["settlement"]["id"]
    r = admin_client.post(f"/api/settlement/{sid}/share-draft", headers=FETCH)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_frozen"
    r = admin_client.request("DELETE", f"/api/settlement/{sid}/share-draft", headers=FETCH)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_shared"

    # once posted it is no longer a draft to share
    sid2 = _build_frozen_settlement(admin_client, m1)
    assert admin_client.post(f"/api/settlement/{sid2}/post", headers=FETCH).status_code == 200
    r = admin_client.post(f"/api/settlement/{sid2}/share-draft", headers=FETCH)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "not_draft"
