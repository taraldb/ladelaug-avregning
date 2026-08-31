"""HTTP surface for member refunds (US-505) — POST /api/members/{id}/refunds."""

from __future__ import annotations

FETCH = {"X-Requested-With": "fetch"}


def _pay(client, member_id, amount="1000.00"):
    return client.post(f"/api/members/{member_id}/payments", json={"amount": amount}, headers=FETCH)


def test_refund_happy_path(admin_client, make_member):
    m = make_member(member_reference="R-1")
    assert _pay(admin_client, m).status_code == 201

    resp = admin_client.post(
        f"/api/members/{m}/refunds",
        json={"amount": "250.00", "value_date": "2026-08-20", "reference": "utbet-42"},
        headers=FETCH,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["txn_type"] == "refund"
    assert body["amount_ore"] == -25000
    assert body["reference"] == "utbet-42"

    bal = admin_client.get(f"/api/members/{m}/balance").json()
    assert bal["balance_nok"] == "750.00"


def test_refund_defaults_value_date_and_optional_reference(admin_client, make_member):
    m = make_member(member_reference="R-2")
    _pay(admin_client, m)
    resp = admin_client.post(f"/api/members/{m}/refunds", json={"amount": "10.00"}, headers=FETCH)
    assert resp.status_code == 201
    assert resp.json()["reference"] is None
    assert resp.json()["value_date"]  # server-filled


def test_refund_exceeding_balance_blocked_then_overridable(admin_client, make_member):
    m = make_member(member_reference="R-3")
    _pay(admin_client, m, amount="100.00")

    blocked = admin_client.post(
        f"/api/members/{m}/refunds", json={"amount": "250.00"}, headers=FETCH
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "refund_exceeds_balance"

    ok = admin_client.post(
        f"/api/members/{m}/refunds",
        json={"amount": "250.00", "allow_negative": True},
        headers=FETCH,
    )
    assert ok.status_code == 201
    assert admin_client.get(f"/api/members/{m}/balance").json()["balance_nok"] == "-150.00"


def test_refund_non_positive_amount_422(admin_client, make_member):
    m = make_member(member_reference="R-4")
    resp = admin_client.post(f"/api/members/{m}/refunds", json={"amount": "0"}, headers=FETCH)
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "validation_error"


def test_refund_unknown_member_404(admin_client):
    assert (
        admin_client.post(
            "/api/members/9999/refunds", json={"amount": "1.00"}, headers=FETCH
        ).status_code
        == 404
    )


def test_refund_requires_csrf_header(admin_client, make_member):
    m = make_member(member_reference="R-5")
    resp = admin_client.post(f"/api/members/{m}/refunds", json={"amount": "1.00"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "csrf"


def test_refund_anonymous_401(client, make_member):
    m = make_member(member_reference="R-6")
    assert (
        client.post(f"/api/members/{m}/refunds", json={"amount": "1.00"}, headers=FETCH).status_code
        == 401
    )


def test_refund_member_403(member_client, make_member):
    m = make_member(member_reference="R-7")
    assert (
        member_client.post(
            f"/api/members/{m}/refunds", json={"amount": "1.00"}, headers=FETCH
        ).status_code
        == 403
    )
