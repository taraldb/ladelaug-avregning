"""Charging-access status (US-305) and its member notifications (US-1003/1004)."""

from __future__ import annotations

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.domain.access import AccessRepo
from ladelaug_avregning.domain.members import MemberRepo
from ladelaug_avregning.errors import DomainError, NotFoundError

SYS = AuditContext.system()
FETCH = {"X-Requested-With": "fetch"}


async def _member(db, ref, email="m@example.com"):
    row = await MemberRepo(db).create(
        member_reference=ref,
        full_name=f"Name {ref}",
        email=email,
        join_date="2026-01-01",
        actor=SYS,
    )
    return int(row["id"])


async def test_warn_records_event_queues_email_and_audits(db):
    m = await _member(db, "AC-1", email="ac1@example.com")
    row = await AccessRepo(db).record(
        m, "warned", reason="ubetalt saldo", portal_url="https://portal.zaptec.com", actor=SYS
    )
    assert row["action"] == "warned"
    assert row["email_message_id"] is not None

    msg = db.connection.execute(
        "SELECT to_address, subject, body_text, template FROM email_messages WHERE id = ?",
        (row["email_message_id"],),
    ).fetchone()
    assert msg["to_address"] == "ac1@example.com"
    assert msg["template"] == "access_warned"
    assert "portal.zaptec.com" in msg["body_text"]
    assert "ubetalt saldo" in msg["body_text"]

    ev = db.connection.execute(
        "SELECT event_type FROM audit_events WHERE event_type = 'access.warned'"
    ).fetchone()
    assert ev is not None
    assert AccessRepo(db).current(m) == "warned"


async def test_disable_records_no_email(db):
    m = await _member(db, "AC-2", email="ac2@example.com")
    row = await AccessRepo(db).record(m, "disabled", reason="gjentatte varsler", actor=SYS)
    assert row["email_message_id"] is None
    assert db.connection.execute("SELECT COUNT(*) FROM email_messages").fetchone()[0] == 0
    assert AccessRepo(db).current(m) == "disabled"
    assert AccessRepo(db).disabled_count() == 1


async def test_restore_queues_email_and_flips_status(db):
    m = await _member(db, "AC-3", email="ac3@example.com")
    await AccessRepo(db).record(m, "disabled", actor=SYS)
    row = await AccessRepo(db).record(m, "restored", actor=SYS)
    assert row["email_message_id"] is not None
    msg = db.connection.execute(
        "SELECT template FROM email_messages WHERE id = ?", (row["email_message_id"],)
    ).fetchone()
    assert msg["template"] == "access_restored"
    assert AccessRepo(db).current(m) == "restored"
    assert AccessRepo(db).disabled_count() == 0


async def test_bad_action_and_unknown_member(db):
    m = await _member(db, "AC-4")
    with pytest.raises(DomainError):
        await AccessRepo(db).record(m, "banned", actor=SYS)
    with pytest.raises(NotFoundError):
        await AccessRepo(db).record(999999, "warned", actor=SYS)


async def test_warn_without_any_email_address_is_still_recorded(db):
    m = await _member(db, "AC-5", email=None)
    row = await AccessRepo(db).record(m, "warned", actor=SYS)
    assert row["email_message_id"] is None
    assert AccessRepo(db).current(m) == "warned"


def test_access_http_flow(admin_client, make_member):
    m = make_member(member_reference="AC-9", email="ac9@example.com")
    empty = admin_client.get(f"/api/members/{m}/access")
    assert empty.status_code == 200 and empty.json()["status"] is None

    posted = admin_client.post(
        f"/api/members/{m}/access", json={"action": "warned", "reason": "x"}, headers=FETCH
    )
    assert posted.status_code == 200
    body = posted.json()
    assert body["status"] == "warned"
    assert body["event"]["action"] == "warned"
    assert len(body["history"]) == 1

    health = admin_client.get("/api/system/health").json()
    assert health["access"] == {"disabled": 0}
    admin_client.post(f"/api/members/{m}/access", json={"action": "disabled"}, headers=FETCH)
    assert admin_client.get("/api/system/health").json()["access"]["disabled"] == 1


def test_access_requires_csrf_header(admin_client, make_member):
    m = make_member(member_reference="AC-8")
    resp = admin_client.post(f"/api/members/{m}/access", json={"action": "warned"})
    assert resp.status_code == 403 and resp.json()["detail"]["code"] == "csrf"


def test_access_requires_admin(member_client, make_member):
    m = make_member(member_reference="AC-7")
    assert member_client.get(f"/api/members/{m}/access").status_code == 403


def test_me_access_carries_portal_url(member_client):
    resp = member_client.get("/api/me/access")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] is None
    assert body["portal_url"].startswith("http")
