#!/usr/bin/env python
"""Backfill the local dev DB with randomised charging history + minimal posted
settlements for the 11 months before the real August 2026 data, so the admin
"Forbruk" charts have a full rolling window to draw. NOT imported by the app.

    uv run python scripts/seed_demo_charging.py [--db state/ladelaug.db] [--dry-run]

It reads the real August ``charging_sessions`` (``source = 'zaptec'``) as the
shape to jitter around — per (charger, member) it keeps roughly the August
session count and samples August's per-session kWh, then applies a gentle
seasonal multiplier (winter up, summer down) so the series has a visible trend
without drifting far from reality. Each seeded month also gets one ``posted``
settlement carrying ``grid_kwh`` / ``invoice_kwh`` / ``invoice_total_nok`` and a
single ``consumption`` invoice line, priced off August's effective kr/kWh.

Everything it writes is tagged for clean removal and it never touches August,
the ledger, or member balances:

    DELETE FROM charging_sessions WHERE source = 'seed';
    DELETE FROM settlement_invoice_lines WHERE settlement_id IN
        (SELECT id FROM settlements WHERE note = 'seed');
    DELETE FROM settlements WHERE note = 'seed';

Re-running wipes the previous seed first, so it is idempotent. The RNG seed is
fixed, so the numbers are reproducible.
"""

from __future__ import annotations

import argparse
import sqlite3
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from random import Random

DEFAULT_DB = "state/ladelaug.db"
REF_MONTH = "2026-08"
TARGET_MONTHS = [
    "2025-09",
    "2025-10",
    "2025-11",
    "2025-12",
    "2026-01",
    "2026-02",
    "2026-03",
    "2026-04",
    "2026-05",
    "2026-06",
    "2026-07",
]

# Gentle per-month multiplier on both session count and per-session kWh.
SEASON = {
    "01": 1.24,
    "02": 1.18,
    "03": 1.05,
    "04": 0.95,
    "05": 0.86,
    "06": 0.80,
    "07": 0.83,
    "08": 0.90,
    "09": 1.00,
    "10": 1.10,
    "11": 1.19,
    "12": 1.27,
}

START_HOURS = (6, 7, 7, 8, 16, 17, 18, 19, 19, 20, 21, 22, 23, 0, 1)
CENT = Decimal("0.01")
RNG = Random(20260902)


def q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def load_reference(cur: sqlite3.Cursor) -> tuple[dict, dict, float]:
    """August (charger, member) -> [kWh samples], -> user_full_name, and the
    August effective kr/kWh."""
    rows = cur.execute(
        "SELECT charger_id, charger_zaptec_id, member_id, energy_kwh, user_full_name "
        "FROM charging_sessions WHERE period_month = ? AND source = 'zaptec'",
        (REF_MONTH,),
    ).fetchall()
    if not rows:
        raise SystemExit(f"no real {REF_MONTH} charging_sessions to base the seed on")

    samples: dict[tuple, list[float]] = defaultdict(list)
    names: dict[tuple, str] = {}
    for r in rows:
        key = (r["charger_id"], r["charger_zaptec_id"], r["member_id"])
        samples[key].append(float(r["energy_kwh"]))
        names[key] = r["user_full_name"]

    s = cur.execute(
        "SELECT invoice_kwh, invoice_total_nok FROM settlements WHERE period_month = ?",
        (REF_MONTH,),
    ).fetchone()
    if s and s["invoice_kwh"] and float(s["invoice_kwh"]) > 0:
        rate = float(s["invoice_total_nok"]) / float(s["invoice_kwh"])
    else:
        rate = 4.2
    return samples, names, rate


def wipe_previous(cur: sqlite3.Cursor) -> tuple[int, int]:
    old = [int(r["id"]) for r in cur.execute("SELECT id FROM settlements WHERE note = 'seed'")]
    if old:
        marks = ",".join("?" * len(old))
        cur.execute(f"DELETE FROM settlement_invoice_lines WHERE settlement_id IN ({marks})", old)
        cur.execute(f"DELETE FROM settlements WHERE id IN ({marks})", old)
    sessions = cur.execute("DELETE FROM charging_sessions WHERE source = 'seed'").rowcount
    return sessions, len(old)


def seed_month(cur: sqlite3.Cursor, month: str, samples: dict, names: dict, rate: float) -> dict:
    year, mon = (int(x) for x in month.split("-"))
    season = SEASON[month[-2:]] * RNG.uniform(0.93, 1.07)
    now = iso(datetime.now(UTC))

    per_member_kwh: dict[int, Decimal] = defaultdict(lambda: Decimal(0))
    per_member_n: dict[int, int] = defaultdict(int)
    month_kwh = Decimal(0)

    for (charger_id, zid, member_id), energies in samples.items():
        n = max(1, round(len(energies) * season * RNG.uniform(0.8, 1.2)))
        for _ in range(n):
            kwh = q2(
                Decimal(str(max(0.02, RNG.choice(energies) * RNG.uniform(0.75, 1.25) * season)))
            )
            start = datetime(
                year,
                mon,
                RNG.randint(1, 27),
                RNG.choice(START_HOURS),
                RNG.randint(0, 59),
                tzinfo=UTC,
            )
            end = start + timedelta(minutes=RNG.randint(25, 600))
            cur.execute(
                "INSERT INTO charging_sessions (zaptec_session_id, charger_id, charger_zaptec_id, "
                "member_id, period_month, started_at, ended_at, energy_kwh, split_method, "
                "user_full_name, source, imported_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'none', ?, 'seed', ?, ?)",
                (
                    str(uuid.uuid4()),
                    charger_id,
                    zid,
                    member_id,
                    month,
                    iso(start),
                    iso(end),
                    f"{kwh}",
                    names[(charger_id, zid, member_id)],
                    now,
                    now,
                ),
            )
            per_member_kwh[member_id] += kwh
            per_member_n[member_id] += 1
            month_kwh += kwh

    grid = q2(month_kwh)
    invoice_kwh = q2(grid * Decimal(str(RNG.uniform(0.97, 1.06))))
    invoice_total = q2(invoice_kwh * Decimal(str(rate * RNG.uniform(0.90, 1.12))))
    stamp = iso(datetime(year, mon, 28, 12, 0, tzinfo=UTC))

    cur.execute(
        "INSERT INTO settlements (period_month, status, invoice_kwh, invoice_total_nok, grid_kwh, "
        "note, usage_frozen_at, created_at, created_by_user_id, posted_at, posted_by_user_id) "
        "VALUES (?, 'posted', ?, ?, ?, 'seed', ?, ?, 1, ?, 1)",
        (month, f"{invoice_kwh}", f"{invoice_total}", f"{grid}", stamp, stamp, stamp),
    )
    sid = int(cur.lastrowid or 0)
    cur.execute(
        "INSERT INTO settlement_invoice_lines (settlement_id, description, allocation_method, "
        "amount_ore, amount_nok, sort_order, created_at) "
        "VALUES (?, 'Strøm (seed)', 'consumption', ?, ?, 1, ?)",
        (sid, int((invoice_total * 100).to_integral_value()), f"{invoice_total}", stamp),
    )

    return {
        "month": month,
        "sessions": sum(per_member_n.values()),
        "grid": grid,
        "invoice_kwh": invoice_kwh,
        "invoice_total": invoice_total,
        "rate": invoice_total / invoice_kwh if invoice_kwh else Decimal(0),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=DEFAULT_DB, help=f"SQLite path (default: {DEFAULT_DB})")
    ap.add_argument("--dry-run", action="store_true", help="roll back instead of committing")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    samples, names, rate = load_reference(cur)
    print(
        f"August reference: {sum(len(v) for v in samples.values())} sessions, "
        f"{rate:.3f} kr/kWh effective\n"
    )

    wiped_sessions, wiped_settlements = wipe_previous(cur)
    if wiped_sessions or wiped_settlements:
        print(
            f"removed previous seed: {wiped_sessions} sessions, {wiped_settlements} settlements\n"
        )

    print(
        f"{'month':<9}{'sessions':>9}{'grid kWh':>12}{'invoice kWh':>13}"
        f"{'invoice NOK':>13}{'kr/kWh':>9}"
    )
    totals = 0
    for month in TARGET_MONTHS:
        r = seed_month(cur, month, samples, names, rate)
        totals += r["sessions"]
        print(
            f"{r['month']:<9}{r['sessions']:>9}{r['grid']:>12}{r['invoice_kwh']:>13}"
            f"{r['invoice_total']:>13}{r['rate']:>9.2f}"
        )

    print(
        f"\n{totals} sessions + {len(TARGET_MONTHS)} posted settlements across "
        f"{TARGET_MONTHS[0]}..{TARGET_MONTHS[-1]}"
    )

    if args.dry_run:
        con.rollback()
        print("--dry-run: rolled back, nothing written")
    else:
        con.commit()
        print("committed")
    con.close()


if __name__ == "__main__":
    main()
