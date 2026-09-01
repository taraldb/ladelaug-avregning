from __future__ import annotations

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.domain.sync_runs import SyncRunRepo
from ladelaug_avregning.zaptec.sync import ZaptecSync, _chargehistory_to


class RecordingClient:
    """Captures the window ``sync_sessions`` hands to the Zaptec client."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []
        self.closed = False

    async def iter_sessions(self, *, date_from, date_to, installation_id=None, detail_level=1):
        self.calls.append(
            {"date_from": date_from, "date_to": date_to, "installation_id": installation_id}
        )
        return
        yield  # pragma: no cover - makes this an async generator

    async def aclose(self) -> None:
        self.closed = True


def _enabled(config: AppConfig) -> AppConfig:
    return config.model_copy(update={"zaptec": config.zaptec.model_copy(update={"enabled": True})})


@pytest.mark.parametrize(
    ("date_to", "expected"),
    [("2026-08-31", "2026-09-01"), ("2026-02-28", "2026-03-01"), ("2026-12-31", "2027-01-01")],
)
def test_chargehistory_to_advances_one_day(date_to: str, expected: str) -> None:
    assert _chargehistory_to(date_to) == expected


async def test_sync_sessions_widens_to_by_one_day(db, config):
    """Zaptec's ``To`` is an exclusive midnight bound, so the last day of the
    requested window would be dropped unless we advance it (prod, 2026-09-01:
    three 2026-08-31 sessions were missed with ``To=2026-08-31``)."""
    client = RecordingClient()
    await ZaptecSync(db, _enabled(config), client=client).sync_sessions(
        date_from="2026-08-01", date_to="2026-08-31", actor=AuditContext.system()
    )

    assert client.calls == [
        {"date_from": "2026-08-01", "date_to": "2026-09-01", "installation_id": None}
    ]

    # The recorded window keeps the caller's inclusive intent, not the wire value.
    run = SyncRunRepo(db).latest("sessions")
    assert run["window_from"] == "2026-08-01"
    assert run["window_to"] == "2026-08-31"
    assert run["status"] == "ok"
