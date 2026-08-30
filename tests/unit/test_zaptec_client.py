from __future__ import annotations

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
    assert chargers[0].serial_no == "ZAP001" and chargers[0].is_active is True
    assert chargers[1].is_active is False


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
