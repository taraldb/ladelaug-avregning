from __future__ import annotations

import dataclasses
import json

import pytest

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.config import AppConfig
from ladelaug_avregning.domain.chargers import ChargerRepo
from ladelaug_avregning.domain.sync_runs import SyncRunRepo
from ladelaug_avregning.errors import DomainError
from ladelaug_avregning.zaptec.client import ZaptecCharger
from ladelaug_avregning.zaptec.sync import ZaptecSync

FETCH = {"X-Requested-With": "fetch"}


class FakeClient:
    def __init__(self, installations, chargers):
        self._installations = installations
        self._chargers = chargers
        self.closed = False

    async def list_installations(self):
        return self._installations

    async def list_chargers(self, installation_id=None):
        return self._chargers

    async def aclose(self):
        self.closed = True


def _charger(zid, name="C", **kw):
    base = {
        "zaptec_id": zid,
        "name": name,
        "serial_no": "S-" + zid,
        "device_id": "d-" + zid,
        "installation_id": "inst-1",
        "circuit_id": "cir-1",
        "device_type": "Pro",
        "is_active": True,
        "raw": {"Id": zid},
    }
    base.update(kw)
    return ZaptecCharger(**base)


def _enabled_config(config: AppConfig) -> AppConfig:
    return config.model_copy(update={"zaptec": config.zaptec.model_copy(update={"enabled": True})})


async def test_sync_chargers_creates_then_updates(db, config):
    cfg = _enabled_config(config)
    fake = FakeClient(
        [{"Id": "inst-1", "Name": "Sameiet"}],
        [_charger("z-1", "Garasje 1"), _charger("z-2", "Garasje 2")],
    )
    result = await ZaptecSync(db, cfg, client=fake).sync_chargers(actor=AuditContext.system())
    assert result == {
        "installations": 1,
        "chargers_seen": 2,
        "chargers_created": 2,
        "chargers_updated": 0,
    }
    assert {c["zaptec_id"] for c in ChargerRepo(db).list()} == {"z-1", "z-2"}
    inst = db.connection.execute("SELECT * FROM zaptec_installations").fetchall()
    assert len(inst) == 1 and inst[0]["name"] == "Sameiet"

    fake2 = FakeClient(
        [{"Id": "inst-1", "Name": "Sameiet borettslag"}],
        [_charger("z-1", "Garasje 1 (ny)"), _charger("z-2", "Garasje 2")],
    )
    result2 = await ZaptecSync(db, cfg, client=fake2).sync_chargers(actor=AuditContext.system())
    assert result2["chargers_created"] == 0 and result2["chargers_updated"] == 2
    assert ChargerRepo(db).get_by_zaptec_id("z-1")["name"] == "Garasje 1 (ny)"

    runs = SyncRunRepo(db)
    assert runs.latest("chargers")["status"] == "ok"
    assert runs.latest("chargers")["items_seen"] == 2


async def test_sync_passes_device_id_through(db, config):
    cfg = _enabled_config(config)
    fake = FakeClient(
        [{"Id": "inst-1", "Name": "S"}],
        [_charger("z-1", "148C", serial_no="ZPR253707", device_id="ZPR253707")],
    )
    await ZaptecSync(db, cfg, client=fake).sync_chargers(actor=AuditContext.system())

    row = ChargerRepo(db).get_by_zaptec_id("z-1")
    assert row["serial_no"] == "ZPR253707"
    event = db.connection.execute(
        "SELECT detail_json FROM audit_events WHERE event_type = 'charger.synced'"
    ).fetchone()
    assert json.loads(event["detail_json"])["device_id"] == "ZPR253707"


async def test_sync_records_error_run_and_reraises(db, config):
    cfg = _enabled_config(config)

    class Boom(FakeClient):
        async def list_chargers(self, installation_id=None):
            raise RuntimeError("upstream 500")

    with pytest.raises(RuntimeError):
        await ZaptecSync(db, cfg, client=Boom([{"Id": "inst-1"}], [])).sync_chargers(
            actor=AuditContext.system()
        )
    run = SyncRunRepo(db).latest("chargers")
    assert run["status"] == "error" and "upstream 500" in run["error"]


async def test_sync_disabled_raises_503(db, config):
    with pytest.raises(DomainError) as ei:
        await ZaptecSync(db, config, client=FakeClient([], [])).sync_chargers(
            actor=AuditContext.system()
        )
    assert ei.value.code == "zaptec_disabled" and ei.value.status == 503


# --- routes ------------------------------------------------------------


def test_sync_route_disabled_returns_503(admin_client):
    resp = admin_client.post("/api/zaptec/sync/chargers", headers=FETCH)
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "zaptec_disabled"


def test_sync_route_runs_with_fake_client(admin_client, monkeypatch):
    admin_client.app.state.config.zaptec.enabled = True
    fake = FakeClient([{"Id": "inst-1", "Name": "S"}], [_charger("z-9", "Z9")])
    monkeypatch.setattr(ZaptecSync, "_new_client", lambda self: fake)

    resp = admin_client.post("/api/zaptec/sync/chargers", headers=FETCH)
    assert resp.status_code == 200 and resp.json()["chargers_created"] == 1

    status = admin_client.get("/api/zaptec/status").json()
    assert status["enabled"] is True
    assert status["last"]["chargers"]["status"] == "ok"
    assert status["last"]["sessions"] is None


def test_zaptec_routes_require_admin(member_client):
    assert member_client.get("/api/zaptec/status").status_code == 403


def test_dataclasses_charger_is_frozen_shape():
    c = _charger("z-1")
    assert dataclasses.asdict(c)["zaptec_id"] == "z-1"
