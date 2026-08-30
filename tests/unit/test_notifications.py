from __future__ import annotations

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import EmailConfig
from ladelaug_avregning.domain.notifications import NotificationRepo
from ladelaug_avregning.domain.users import UserRepo
from ladelaug_avregning.email.sender import EmailSender

FETCH = {"X-Requested-With": "fetch"}


class FakeSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[str] = []
        self.fail = fail

    async def send(self, *, to: str, subject: str, text: str, html: str | None = None) -> None:
        if self.fail:
            raise RuntimeError("smtp down")
        self.sent.append(to)


# --- EmailSender backends -------------------------------------------


async def test_console_backend_is_noop(caplog):
    sender = EmailSender(EmailConfig(backend="console"))
    await sender.send(to="a@example.com", subject="Hi", text="body")  # no raise


async def test_file_backend_writes_eml(tmp_path):
    sender = EmailSender(EmailConfig(backend="file"), state_dir=tmp_path)
    await sender.send(to="kari@example.com", subject="Avregning", text="hei")
    files = list((tmp_path / "mail").glob("*.eml"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8")
    assert "To: kari@example.com" in content and "hei" in content


# --- NotificationRepo queue --------------------------------------


async def test_enqueue_and_process_success(db):
    repo = NotificationRepo(db)
    await repo.enqueue(to_address="a@example.com", subject="s", body_text="t", template="x")
    sender = FakeSender()
    out = await repo.process_queue(sender)
    assert out == {"due": 1, "sent": 1, "failed": 0, "retried": 0}
    assert sender.sent == ["a@example.com"]
    assert repo.stats()["sent"] == 1 and repo.stats()["queued"] == 0


async def test_failure_retries_then_fails_after_max_attempts(db):
    repo = NotificationRepo(db)
    await repo.enqueue(
        to_address="a@example.com", subject="s", body_text="t", template="x", max_attempts=1
    )
    out = await repo.process_queue(FakeSender(fail=True))
    assert out["failed"] == 1 and out["retried"] == 0
    row = repo.recent()[0]
    assert row["status"] == "failed" and "smtp down" in row["last_error"]


async def test_failure_below_max_reschedules(db):
    repo = NotificationRepo(db)
    mid = await repo.enqueue(
        to_address="a@example.com", subject="s", body_text="t", template="x", max_attempts=3
    )
    out = await repo.process_queue(FakeSender(fail=True))
    assert out["retried"] == 1 and out["failed"] == 0
    row = repo.recent()[0]
    assert row["id"] == mid and row["status"] == "queued" and row["attempts"] == 1
    # backoff pushed it out, so a second immediate drain sees nothing due
    assert (await repo.process_queue(FakeSender()))["due"] == 0


async def test_enqueue_settlement_reports_targets_linked_users(db, config):
    from ladelaug_avregning.domain.members import MemberRepo

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
    m2 = int(
        (
            await MemberRepo(db).create(
                member_reference="A-2",
                full_name="Bo",
                email=None,
                join_date="2026-01-01",
                actor=AuditContext.system(),
            )
        )["id"]
    )
    await UserRepo(db).create(
        email="ada@example.com",
        password="x" * 12,
        role="member",
        member_id=m1,
        actor=AuditContext.system(),
        argon2=(1, 8192, 1),
    )
    # m2 has no user -> skipped

    result = {
        "period_month": "2026-07",
        "members": [
            {
                "member_id": m1,
                "full_name": "Ada",
                "charge_nok": "100.00",
                "balance_after_nok": "900.00",
            },
            {
                "member_id": m2,
                "full_name": "Bo",
                "charge_nok": "50.00",
                "balance_after_nok": "-10.00",
            },
        ],
    }
    queued = await NotificationRepo(db).enqueue_settlement_reports(
        settlement_id=1, result=result, base_url="https://portal.example.com/"
    )
    assert queued == 1
    row = NotificationRepo(db).recent()[0]
    assert row["to_address"] == "ada@example.com"
    assert row["template"] == "settlement_report" and row["related_entity_id"] == "1"


# --- routes ------------------------------------------------------------


def test_system_health_shape(admin_client):
    body = admin_client.get("/api/system/health").json()
    assert body["zaptec"]["enabled"] is False
    assert set(body["email"]) == {"queued", "sent", "failed", "next_attempt_at"}
    assert body["schema_version"] >= 6
    assert body["ok"] is True


def test_notifications_process_and_list(admin_client):
    admin_client.app.state.db.connection.execute(
        "INSERT INTO email_messages (to_address, subject, body_text, status, next_attempt_at, "
        "created_at) VALUES ('x@example.com','s','t','queued','2000-01-01T00:00:00+00:00',"
        "'2000-01-01T00:00:00+00:00')"
    )
    admin_client.app.state.db.connection.commit()
    out = admin_client.post("/api/notifications/process", headers=FETCH).json()
    assert out["sent"] == 1
    assert admin_client.get("/api/notifications").json()["stats"]["sent"] == 1


def test_system_and_notifications_require_admin(member_client):
    assert member_client.get("/api/system/health").status_code == 403
    assert member_client.get("/api/notifications").status_code == 403


def test_notifications_process_needs_fetch_header(admin_client):
    assert admin_client.post("/api/notifications/process").status_code == 403
