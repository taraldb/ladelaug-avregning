"""HTTP surface for settlement corrections (Epic 7).

GET  /api/settlement/{id}/correction   — assess (US-701/702)
POST /api/settlement/{id}/correction   — book + notify (US-703)
"""

from __future__ import annotations

FETCH = {"X-Requested-With": "fetch"}
MONTH = "2026-07"


def _session(client, *, sid_str, member_id, kwh):
    client.app.state.db.connection.execute(
        "INSERT INTO charging_sessions "
        "(zaptec_session_id, charger_zaptec_id, member_id, period_month, started_at, ended_at, "
        " energy_kwh, split_method, source, imported_at, updated_at) "
        "VALUES (?, 'z1', ?, ?, '2026-07-10T10:00:00+00:00', '2026-07-10T12:00:00+00:00', "
        "?, 'none', 'test', 'x', 'x')",
        (sid_str, member_id, MONTH, str(kwh)),
    )
    client.app.state.db.connection.commit()


def _post_settlement(admin_client, make_member, seed_user_sync):
    m1 = make_member(member_reference="M1", email="m1@example.com")
    m2 = make_member(member_reference="M2", email="m2@example.com")
    for m, addr in ((m1, "m1@example.com"), (m2, "m2@example.com")):
        seed_user_sync(email=addr, role="member", member_id=m)
        admin_client.post(
            f"/api/members/{m}/status",
            json={"status": "active", "effective_from": "2026-01-01"},
            headers=FETCH,
        )
    _session(admin_client, sid_str="s1", member_id=m1, kwh=10)
    _session(admin_client, sid_str="s2", member_id=m2, kwh=10)

    sid = admin_client.post(
        "/api/settlement/drafts", json={"period_month": MONTH}, headers=FETCH
    ).json()["settlement"]["id"]
    admin_client.post(
        f"/api/settlement/{sid}/lines",
        json={"description": "Energi", "allocation_method": "consumption", "amount": "1000"},
        headers=FETCH,
    )
    admin_client.put(f"/api/settlement/{sid}/invoice", json={"invoice_kwh": "20"}, headers=FETCH)
    admin_client.post(
        f"/api/settlement/{sid}/attachments",
        files={"files": ("f.pdf", b"%PDF fake", "application/pdf")},
        headers=FETCH,
    )
    admin_client.post(f"/api/settlement/{sid}/freeze", headers=FETCH)
    admin_client.post(f"/api/settlement/{sid}/post", headers=FETCH)
    return sid, m1, m2


def test_assess_reports_no_change_then_a_shift(admin_client, make_member, seed_user_sync):
    sid, m1, m2 = _post_settlement(admin_client, make_member, seed_user_sync)

    a = admin_client.get(f"/api/settlement/{sid}/correction")
    assert a.status_code == 200
    assert a.json()["has_changes"] is False

    _session(admin_client, sid_str="s-late", member_id=m1, kwh=10)
    a2 = admin_client.get(f"/api/settlement/{sid}/correction").json()
    assert a2["has_changes"] is True
    by_id = {m["member_id"]: m for m in a2["members"]}
    assert by_id[m1]["delta_ore"] + by_id[m2]["delta_ore"] == 0


def test_post_correction_books_rows_and_queues_email(admin_client, make_member, seed_user_sync):
    sid, m1, _m2 = _post_settlement(admin_client, make_member, seed_user_sync)
    _session(admin_client, sid_str="s-late", member_id=m1, kwh=10)

    resp = admin_client.post(f"/api/settlement/{sid}/correction", headers=FETCH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["sequence"] == 1
    assert body["members_adjusted"] == 2
    assert body["emails_queued"] == 2

    detail = admin_client.get(f"/api/settlement/{sid}").json()
    assert len(detail["corrections"]) == 1
    assert detail["correction_pending"] is False

    # a second post with nothing new -> 422
    again = admin_client.post(f"/api/settlement/{sid}/correction", headers=FETCH)
    assert again.status_code == 422
    assert again.json()["detail"]["code"] == "no_correction_needed"


def test_correction_on_draft_is_rejected(admin_client, make_member):
    m1 = make_member(member_reference="M1")
    admin_client.post(
        f"/api/members/{m1}/status",
        json={"status": "active", "effective_from": "2026-01-01"},
        headers=FETCH,
    )
    sid = admin_client.post(
        "/api/settlement/drafts", json={"period_month": MONTH}, headers=FETCH
    ).json()["settlement"]["id"]
    resp = admin_client.get(f"/api/settlement/{sid}/correction")
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "not_posted"


def test_correction_needs_csrf_header_and_auth(admin_client, client, make_member, seed_user_sync):
    sid, _m1, _m2 = _post_settlement(admin_client, make_member, seed_user_sync)
    assert admin_client.post(f"/api/settlement/{sid}/correction").status_code == 403
    client.cookies.clear()
    assert client.get(f"/api/settlement/{sid}/correction").status_code == 401
