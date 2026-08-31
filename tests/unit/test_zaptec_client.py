from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
import respx

from ladelaug_avregning.config import ZaptecConfig
from ladelaug_avregning.zaptec.client import (
    ZaptecAuthError,
    ZaptecClient,
    ZaptecError,
)

BASE = "https://api.zaptec.com"


def _cfg(**kw) -> ZaptecConfig:
    return ZaptecConfig(
        enabled=True,
        username="u@example.com",
        password="pw",
        max_retries=3,
        page_size=2,
        **kw,
    )


def _token_route(respx_mock) -> None:
    respx_mock.post(f"{BASE}/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
    )


@respx.mock
async def test_authenticate_sends_password_grant(respx_mock):
    route = respx_mock.post(f"{BASE}/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "abc", "expires_in": 3600})
    )
    async with ZaptecClient(_cfg()) as client:
        await client.authenticate()
    assert route.called
    sent = route.calls.last.request
    assert b"grant_type=password" in sent.content
    assert b"u%40example.com" in sent.content


@respx.mock
async def test_bad_credentials_raise_auth_error(respx_mock):
    respx_mock.post(f"{BASE}/oauth/token").mock(return_value=httpx.Response(400))
    async with ZaptecClient(_cfg()) as client:
        with pytest.raises(ZaptecAuthError):
            await client.authenticate()


@respx.mock
async def test_list_chargers_parses_and_follows_pagination(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/chargers").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "Pages": 2,
                    "Data": [
                        {
                            "Id": "c-1",
                            "Name": "Garasje 1",
                            "SerialNo": "ZAP001",
                            "DeviceId": "d-1",
                            "InstallationId": "inst-1",
                            "CircuitId": "cir-1",
                            "DeviceType": "Pro",
                        }
                    ],
                },
            ),
            httpx.Response(
                200,
                json={
                    "Pages": 2,
                    "Data": [
                        {"Id": "c-2", "Name": "Garasje 2", "Deleted": True},
                    ],
                },
            ),
        ]
    )
    async with ZaptecClient(_cfg()) as client:
        chargers = await client.list_chargers("inst-1")
    assert [c.zaptec_id for c in chargers] == ["c-1", "c-2"]
    # serial_no comes from the hardware DeviceId, not the installer-set SerialNo.
    assert chargers[0].serial_no == "d-1" and chargers[0].device_id == "d-1"
    assert chargers[0].is_active is True
    assert chargers[1].is_active is False


@respx.mock
async def test_list_chargers_serial_falls_back_and_prefers_device_id(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/chargers").mock(
        return_value=httpx.Response(
            200,
            json={
                "Pages": 1,
                "Data": [
                    # SerialNo duplicates Name (the installation this bug was
                    # found in); the ZPR… hardware id is in DeviceId.
                    {"Id": "c-1", "Name": "148C", "SerialNo": "148C", "DeviceId": "ZPR253707"},
                    # No DeviceId — fall back to SerialNo.
                    {"Id": "c-2", "Name": "148D", "SerialNo": "ZPR999"},
                ],
            },
        )
    )
    async with ZaptecClient(_cfg()) as client:
        chargers = await client.list_chargers("inst-1")
    assert chargers[0].serial_no == "ZPR253707"
    assert chargers[1].serial_no == "ZPR999"


@respx.mock
async def test_iter_sessions_normalises_timestamps_and_intervals(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/chargehistory").mock(
        return_value=httpx.Response(
            200,
            json={
                "Pages": 1,
                "Data": [
                    {
                        "Id": "s-1",
                        "ChargerId": "c-1",
                        "DeviceId": "d-1",
                        "StartDateTime": "2026-07-01T22:45:00",
                        "EndDateTime": "2026-07-01T23:30:00Z",
                        "Energy": 7.5,
                        "UserId": "u-9",
                        "UserFullName": "Kari",
                        "EnergyDetails": [
                            {"Timestamp": "2026-07-01T22:45:00", "Energy": 2.5},
                            {"Timestamp": "2026-07-01T23:00:00", "Energy": 5.0},
                        ],
                    }
                ],
            },
        )
    )
    async with ZaptecClient(_cfg()) as client:
        sessions = [
            s
            async for s in client.iter_sessions(
                date_from="2026-07-01", date_to="2026-08-01", installation_id="inst-1"
            )
        ]
    assert len(sessions) == 1
    s = sessions[0]
    assert s.started_at == "2026-07-01T22:45:00+00:00"
    assert s.ended_at == "2026-07-01T23:30:00+00:00"
    assert s.energy_kwh == Decimal("7.5")
    assert [p.energy_kwh for p in s.energy_details] == [Decimal("2.5"), Decimal("5.0")]


@respx.mock
async def test_retries_on_500_then_succeeds(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/installation").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, json={"Pages": 1, "Data": [{"Id": "inst-1", "Name": "Sameiet"}]}),
        ]
    )
    async with ZaptecClient(_cfg()) as client:
        installations = await client.list_installations()
    assert installations == [{"Id": "inst-1", "Name": "Sameiet"}]


@respx.mock
async def test_reauths_once_on_401(respx_mock):
    tokens = respx_mock.post(f"{BASE}/oauth/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "old", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "new", "expires_in": 3600}),
        ]
    )
    respx_mock.get(f"{BASE}/api/chargers").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"Pages": 1, "Data": []})]
    )
    async with ZaptecClient(_cfg()) as client:
        await client.list_chargers()
    assert tokens.call_count == 2


@respx.mock
async def test_4xx_other_than_401_raises(respx_mock):
    _token_route(respx_mock)
    respx_mock.get(f"{BASE}/api/chargers").mock(return_value=httpx.Response(404, text="nope"))
    async with ZaptecClient(_cfg()) as client:
        with pytest.raises(ZaptecError):
            await client.list_chargers()


@respx.mock
async def test_capture_dir_writes_redacted_json(respx_mock, tmp_path):
    respx_mock.post(f"{BASE}/oauth/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok-secret", "expires_in": 3600})
    )
    respx_mock.get(f"{BASE}/api/chargehistory").mock(
        return_value=httpx.Response(
            200,
            json={
                "Pages": 1,
                "Data": [
                    {
                        "Id": "s-1",
                        "ChargerId": "c-1",
                        "StartDateTime": "2026-08-30T14:21:00Z",
                        "EndDateTime": "2026-08-31T06:26:00Z",
                        "Energy": 19.35,
                    }
                ],
            },
        )
    )
    async with ZaptecClient(_cfg(capture_dir=str(tmp_path))) as client:
        _ = [s async for s in client.iter_sessions(date_from="2026-08-01", date_to="2026-09-01")]

    files = sorted(tmp_path.glob("*.json"))
    assert len(files) == 2  # the token POST + one chargehistory GET page

    token = json.loads(next(f for f in files if "oauth" in f.name).read_text())
    assert token["method"] == "POST"
    assert token["request_body"]["password"] == "<redacted>"
    assert token["request_body"]["username"] == "u@example.com"
    assert token["response_json"]["access_token"] == "<redacted>"

    hist = json.loads(next(f for f in files if "chargehistory" in f.name).read_text())
    assert hist["method"] == "GET" and hist["status"] == 200
    assert hist["request_headers"]["Authorization"] == "<redacted>"
    assert hist["params"]["From"] == "2026-08-01" and hist["params"]["To"] == "2026-09-01"
    assert hist["response_json"]["Data"][0]["Energy"] == 19.35
    assert isinstance(hist["elapsed_ms"], (int, float))


async def test_capture_dir_off_by_default(tmp_path):
    client = ZaptecClient(_cfg())
    assert client._capture_dir is None
    await client.aclose()
