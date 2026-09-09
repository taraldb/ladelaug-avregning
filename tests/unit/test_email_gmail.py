"""The ``gmail`` EmailSender backend: OAuth2 refresh-token flow + Gmail REST send.

Mirrors ``test_zaptec_client`` — HTTP is mocked with ``respx`` and an
``httpx.AsyncClient`` is injected into the sender.
"""

from __future__ import annotations

import base64
from datetime import timedelta
from email import message_from_bytes

import httpx
import pytest
import respx

from ladelaug_avregning import clock
from ladelaug_avregning.config import EmailConfig
from ladelaug_avregning.email.sender import EmailSender

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def _cfg(**kw) -> EmailConfig:
    return EmailConfig(
        backend="gmail",
        from_address="ladelaug@example.com",
        gmail_client_id="cid",
        gmail_client_secret="secret",
        gmail_refresh_token="rt",
        gmail_sender="coop@gmail.com",
        **kw,
    )


def _decoded_raw(request: httpx.Request):
    body = request.read()
    import json

    raw = json.loads(body)["raw"]
    return message_from_bytes(base64.urlsafe_b64decode(raw))


@respx.mock
async def test_send_refreshes_token_then_posts_message(respx_mock):
    token = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
    )
    send = respx_mock.post(SEND_URL).mock(return_value=httpx.Response(200, json={"id": "m1"}))

    async with httpx.AsyncClient() as http:
        sender = EmailSender(_cfg(), http=http)
        await sender.send(to="kari@example.com", subject="Avregning", text="hei", html="<p>hei</p>")

    assert token.called
    grant = token.calls.last.request.read()
    assert b"grant_type=refresh_token" in grant
    assert b"refresh_token=rt" in grant

    assert send.called
    assert send.calls.last.request.headers["Authorization"] == "Bearer at-1"
    msg = _decoded_raw(send.calls.last.request)
    assert msg["To"] == "kari@example.com"
    assert msg["Subject"] == "Avregning"
    assert msg["From"] == "coop@gmail.com"  # gmail_sender overrides from_address
    assert msg.is_multipart()
    assert {p.get_content_type() for p in msg.walk()} >= {"text/plain", "text/html"}


@respx.mock
async def test_token_is_cached_across_sends(respx_mock):
    token = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at-1", "expires_in": 3600})
    )
    respx_mock.post(SEND_URL).mock(return_value=httpx.Response(200, json={"id": "m"}))

    async with httpx.AsyncClient() as http:
        sender = EmailSender(_cfg(), http=http)
        await sender.send(to="a@example.com", subject="s", text="t")
        await sender.send(to="b@example.com", subject="s", text="t")

    assert token.call_count == 1


@respx.mock
async def test_expired_token_is_refreshed(respx_mock):
    token = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
    )
    respx_mock.post(SEND_URL).mock(return_value=httpx.Response(200, json={"id": "m"}))

    async with httpx.AsyncClient() as http:
        sender = EmailSender(_cfg(), http=http)
        await sender.send(to="a@example.com", subject="s", text="t")
        sender._gmail_token_expiry = clock.now_utc() - timedelta(seconds=1)
        await sender.send(to="b@example.com", subject="s", text="t")

    assert token.call_count == 2


@respx.mock
async def test_401_on_send_triggers_one_refresh_and_retry(respx_mock):
    token = respx_mock.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "stale", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600}),
        ]
    )
    send = respx_mock.post(SEND_URL).mock(
        side_effect=[httpx.Response(401, json={"error": "invalid"}), httpx.Response(200)]
    )

    async with httpx.AsyncClient() as http:
        sender = EmailSender(_cfg(), http=http)
        await sender.send(to="a@example.com", subject="s", text="t")

    assert token.call_count == 2
    assert send.call_count == 2
    assert send.calls.last.request.headers["Authorization"] == "Bearer fresh"


@respx.mock
async def test_persistent_send_error_raises(respx_mock):
    respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
    )
    respx_mock.post(SEND_URL).mock(return_value=httpx.Response(500, text="boom"))

    async with httpx.AsyncClient() as http:
        sender = EmailSender(_cfg(), http=http)
        with pytest.raises(RuntimeError, match="Gmail send failed"):
            await sender.send(to="a@example.com", subject="s", text="t")


@respx.mock
async def test_token_refresh_failure_raises(respx_mock):
    respx_mock.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "bad_grant"}))

    async with httpx.AsyncClient() as http:
        sender = EmailSender(_cfg(), http=http)
        with pytest.raises(RuntimeError, match="Gmail token refresh failed"):
            await sender.send(to="a@example.com", subject="s", text="t")


@respx.mock
async def test_check_gmail_credentials_ok(respx_mock):
    token = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
    )
    send = respx_mock.post(SEND_URL)

    async with httpx.AsyncClient() as http:
        out = await EmailSender(_cfg(), http=http).check_gmail_credentials()

    assert out["ok"] is True
    assert out["sender"] == "coop@gmail.com"
    assert b"grant_type=refresh_token" in token.calls.last.request.read()
    assert not send.called  # a probe never sends a message


@respx.mock
async def test_check_gmail_credentials_bypasses_the_cache(respx_mock):
    token = respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
    )

    async with httpx.AsyncClient() as http:
        sender = EmailSender(_cfg(), http=http)
        sender._gmail_token = "cached"
        sender._gmail_token_expiry = clock.now_utc() + timedelta(hours=1)
        await sender.check_gmail_credentials()

    assert token.call_count == 1  # went to Google despite a live cached token


@respx.mock
async def test_check_gmail_credentials_raises_on_revoked_token(respx_mock):
    respx_mock.post(TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )

    async with httpx.AsyncClient() as http:
        sender = EmailSender(_cfg(), http=http)
        with pytest.raises(RuntimeError, match="Gmail token refresh failed"):
            await sender.check_gmail_credentials()


async def test_check_gmail_credentials_skips_non_gmail_backend():
    cfg = EmailConfig(backend="console", from_address="ladelaug@example.com")
    out = await EmailSender(cfg).check_gmail_credentials()
    assert out == {"skipped": "backend_not_gmail", "backend": "console"}
