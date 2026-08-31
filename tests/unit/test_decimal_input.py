"""Every numeric-amount endpoint accepts a comma OR a period decimal separator
(and space/point thousands separators) — "123,45" and "123.45" both mean
123 NOK 45 øre.
"""

from __future__ import annotations

FETCH = {"X-Requested-With": "fetch"}
MONTH = "2026-07"


def test_payment_accepts_comma_decimal(admin_client, make_member):
    m = make_member(member_reference="D-1")
    resp = admin_client.post(f"/api/members/{m}/payments", json={"amount": "123,45"}, headers=FETCH)
    assert resp.status_code == 201
    assert resp.json()["amount_nok"] == "123.45"
    assert admin_client.get(f"/api/members/{m}/balance").json()["balance_nok"] == "123.45"


def test_adjustment_and_refund_accept_comma(admin_client, make_member):
    m = make_member(member_reference="D-2")
    admin_client.post(f"/api/members/{m}/payments", json={"amount": "1000"}, headers=FETCH)
    adj = admin_client.post(
        f"/api/members/{m}/adjustments",
        json={"direction": "credit", "amount": "10,50", "reason": "x"},
        headers=FETCH,
    )
    assert adj.status_code == 201 and adj.json()["amount_nok"] == "10.50"
    ref = admin_client.post(f"/api/members/{m}/refunds", json={"amount": "1 000,50"}, headers=FETCH)
    assert ref.status_code == 201 and ref.json()["amount_nok"] == "-1000.50"


def test_invoice_line_amount_and_kwh_accept_comma(admin_client):
    sid = admin_client.post(
        "/api/settlement/drafts", json={"period_month": MONTH}, headers=FETCH
    ).json()["settlement"]["id"]

    line = admin_client.post(
        f"/api/settlement/{sid}/lines",
        json={"description": "Fast", "allocation_method": "equal", "amount": "1.234,50"},
        headers=FETCH,
    )
    assert line.status_code == 201 and line.json()["line"]["amount_nok"] == "1234.50"

    patched = admin_client.patch(
        f"/api/settlement/{sid}/lines/{line.json()['line']['id']}",
        json={"amount": "-99,9"},
        headers=FETCH,
    )
    assert patched.status_code == 200
    assert patched.json()["lines"][0]["amount_nok"] == "-99.90"

    detail = admin_client.put(
        f"/api/settlement/{sid}/invoice", json={"invoice_kwh": "12,5"}, headers=FETCH
    )
    assert detail.status_code == 200
    assert detail.json()["settlement"]["invoice_kwh"] == "12.50"


def test_forecast_buffer_months_accepts_comma(admin_client):
    resp = admin_client.put("/api/forecast/settings", json={"buffer_months": "2,5"}, headers=FETCH)
    assert resp.status_code == 200
    assert resp.json()["buffer_months"] == 2.5
