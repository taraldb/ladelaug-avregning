#!/usr/bin/env python
"""One-time OAuth2 bootstrap for the ``gmail`` email backend.

Mints a long-lived **refresh token** for the Gmail REST API (scope
``gmail.send`` only). Run it once on a machine with a browser; paste the printed
token into ``.env`` as ``GMAIL_REFRESH_TOKEN``. It is NOT imported by the app.

Prerequisites (Google Cloud console, one-time):
  1. Create / pick a project, enable the **Gmail API**.
  2. Configure the OAuth consent screen (External is fine; add your own Google
     account as a test user so it works without verification).
  3. Create an **OAuth client ID** of type **Desktop app**. Note its client id
     and client secret.

    export GMAIL_CLIENT_ID=...            # or pass --client-id
    export GMAIL_CLIENT_SECRET=...        # or pass --client-secret
    uv run python scripts/gmail_oauth_bootstrap.py

A browser window opens for consent; the script captures the redirect on
``http://localhost:<port>``, exchanges the code, and prints the refresh token.
"""

from __future__ import annotations

import argparse
import http.server
import os
import sys
import threading
import urllib.parse
import webbrowser

import httpx

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/gmail.send"


class _CaptureHandler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CaptureHandler.code = (params.get("code") or [None])[0]
        _CaptureHandler.error = (params.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = (
            "<h2>Gmail bootstrap complete.</h2><p>You can close this tab and "
            "return to the terminal.</p>"
            if _CaptureHandler.code
            else f"<h2>Authorization failed:</h2><pre>{_CaptureHandler.error}</pre>"
        )
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *_args: object) -> None:  # silence the default access log
        return


def _capture_code(redirect_port: int) -> str:
    server = http.server.HTTPServer(("localhost", redirect_port), _CaptureHandler)
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    thread.join(timeout=300)
    server.server_close()
    if _CaptureHandler.error:
        sys.exit(f"Authorization denied: {_CaptureHandler.error}")
    if not _CaptureHandler.code:
        sys.exit("Timed out waiting for the OAuth redirect.")
    return _CaptureHandler.code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-id", default=os.environ.get("GMAIL_CLIENT_ID", ""))
    parser.add_argument("--client-secret", default=os.environ.get("GMAIL_CLIENT_SECRET", ""))
    parser.add_argument("--port", type=int, default=8765, help="loopback redirect port")
    args = parser.parse_args(argv)
    if not (args.client_id and args.client_secret):
        parser.error(
            "client id/secret required (--client-id/--client-secret or GMAIL_CLIENT_* env)"
        )

    redirect_uri = f"http://localhost:{args.port}"
    auth_url = (
        _AUTH_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": args.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": _SCOPE,
                "access_type": "offline",
                "prompt": "consent",
            }
        )
    )
    print(f"Opening browser for consent; if it does not open, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)
    code = _capture_code(args.port)

    resp = httpx.post(
        _TOKEN_URL,
        data={
            "code": code,
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if resp.status_code >= 300:
        sys.exit(f"Token exchange failed ({resp.status_code}): {resp.text}")
    body = resp.json()
    refresh_token = body.get("refresh_token")
    if not refresh_token:
        sys.exit(
            "No refresh_token in the response (Google only returns one on first consent — "
            "revoke the app's access at https://myaccount.google.com/permissions and retry)."
        )
    print("\nAdd this to .env:\n")
    print(f"GMAIL_REFRESH_TOKEN={refresh_token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
