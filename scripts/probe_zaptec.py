#!/usr/bin/env python
"""Throwaway probe against a real Zaptec installation.

Run this once, before trusting the adapter in production, to confirm the wire
shapes the client in ``ladelaug_avregning.zaptec.client`` assumes. It is NOT
imported by the app.

    export ZAPTEC_PASSWORD=...            # or put it in .env
    uv run python scripts/probe_zaptec.py --username you@example.com \
        [--installation <uuid>] [--from 2026-07-01 --to 2026-08-01]

It prints, for each endpoint, the HTTP status, pagination envelope keys, and the
key set of the first item (plus one full pretty-printed sample), so the findings
can be pasted into spec/release-1b-plan.md § Probe findings.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta

import httpx

from ladelaug_avregning.config import ZaptecConfig
from ladelaug_avregning.zaptec.client import ZaptecClient


def _keys(obj: object) -> object:
    if isinstance(obj, dict):
        return sorted(obj.keys())
    if isinstance(obj, list) and obj:
        return [_keys(obj[0]), f"... {len(obj)} items"]
    return type(obj).__name__


def _sample(obj: object, limit: int = 2000) -> str:
    text = json.dumps(obj, indent=2, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"


async def _run(args: argparse.Namespace) -> int:
    password = os.environ.get("ZAPTEC_PASSWORD", "")
    if not password:
        print("ZAPTEC_PASSWORD is not set (env or .env).", file=sys.stderr)
        return 2

    cfg = ZaptecConfig(
        enabled=True,
        username=args.username,
        password=password,
        installation_id=args.installation or "",
        page_size=args.page_size,
    )

    date_to = args.to or datetime.now(UTC).date().isoformat()
    date_from = args.from_ or (datetime.now(UTC) - timedelta(days=35)).date().isoformat()

    async with httpx.AsyncClient(timeout=cfg.request_timeout_seconds) as http:
        client = ZaptecClient(cfg, http=http)

        print("== POST /oauth/token ==")
        await client.authenticate()
        print("  ok — token acquired\n")

        print("== GET /api/installation ==")
        installations = await client.list_installations()
        print(f"  {len(installations)} installation(s); first keys: {_keys(installations)}")
        if installations:
            print(_sample(installations[0]))
        chosen = cfg.installation_id or (str(installations[0]["Id"]) if installations else "")
        print(f"  using installation_id = {chosen or '(none)'}\n")

        print("== GET /api/chargers ==")
        chargers = await client.list_chargers(chosen or None)
        print(f"  {len(chargers)} charger(s)")
        if chargers:
            print("  parsed[0]:", chargers[0])
            print("  raw[0] keys:", _keys(chargers[0].raw))
            print(_sample(chargers[0].raw))
        print()

        print(f"== GET /api/chargehistory  From={date_from} To={date_to} DetailLevel=1 ==")
        count = 0
        first = None
        async for session in client.iter_sessions(
            date_from=date_from, date_to=date_to, installation_id=chosen or None
        ):
            count += 1
            if first is None:
                first = session
        print(f"  {count} session(s)")
        if first is not None:
            print("  parsed[0]:", first)
            print(f"  energy_details points on [0]: {len(first.energy_details)}")
            if first.energy_details:
                print("  first interval point:", first.energy_details[0])
            print("  raw[0] keys:", _keys(first.raw))
            print(_sample(first.raw))
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--username", required=True)
    p.add_argument("--installation", default=None)
    p.add_argument("--from", dest="from_", default=None, help="YYYY-MM-DD (default: 35 days ago)")
    p.add_argument("--to", default=None, help="YYYY-MM-DD (default: today)")
    p.add_argument("--page-size", type=int, default=100)
    return asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
