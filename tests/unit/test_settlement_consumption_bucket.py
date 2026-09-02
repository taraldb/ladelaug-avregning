"""Every ``consumption`` invoice line is pooled into one bucket and divided by
kWh share exactly once, so the per-member charge does not depend on how the
supplier costs are itemised and the øre rounding drift is applied once, not once
per line.

The three scenarios below describe the *same* month — total charging 591.33 kWh
split 126.22 / 73.9 / 189.92 / 201.29, one equal ``kapasitetsledd`` of 650 kr,
and 536.65 kr of consumption cost — itemised three different ways:

* six supplier lines (Strøm, energiledd dag/natt, energifond, norgespris,
  forbruksavgift);
* three lines (Strøm, Nettleie = the four grid lines pooled, Norgespris);
* one line (Forbruk = everything pooled).

They must produce identical per-member charges.
"""

from __future__ import annotations

import random
from decimal import Decimal
from pathlib import Path

from ladelaug_avregning.audit import AuditContext
from ladelaug_avregning.db import Database
from ladelaug_avregning.domain.settlement import CONSUMPTION_LINE_LABEL, SettlementRepo
from ladelaug_avregning.money import allocate_by_weights, nok_to_ore

from .test_settlement_engine import MONTH, _add_consumption, _member

_MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

KWH = ("126.22", "73.9", "189.92", "201.29")  # sums to 591.33
EQUAL_NOK = "650"

SIX = [
    ("Strøm", "1160.92"),
    ("Energiledd dag", "77.09"),
    ("Energiledd natt", "63.57"),
    ("Energifond", "7.69"),
    ("Norgespris", "-827.41"),
    ("Forbruksavgift", "54.79"),
]
THREE = [
    ("Strøm", "1160.92"),
    ("Nettleie", "203.14"),  # 77.09 + 63.57 + 7.69 + 54.79
    ("Norgespris", "-827.41"),
]
ONE = [("Forbruk", "536.65")]

# consumption bucket = 536.65 kr = 53665 øre. Exact kWh-weighted shares are
# 11454.85 / 6706.65 / 17235.82 / 18267.68 øre; the floors 11454 / 6706 / 17235 /
# 18267 sum to 53662, and the 3 leftover øre go one each to the largest
# fractional remainders (M0 .85, M2 .82, M3 .68 — not M1 .65) -> 11455 / 6706 /
# 17236 / 18268.
EXPECTED_CONSUMPTION = [11455, 6706, 17236, 18268]
EQUAL_EACH = 16250  # 650 kr / 4, even
EXPECTED_TOTAL = [c + EQUAL_EACH for c in EXPECTED_CONSUMPTION]
INVOICE_TOTAL_ORE = 53665 + 65000  # 118665


def _fresh_db(tmp_path: Path, name: str) -> Database:
    """A migrated SQLite DB of its own — every grouping in a comparison test gets
    an isolated member set so their equal-split denominators do not run together."""
    return Database(str(tmp_path / f"{name}.db"), migrations_dir=_MIGRATIONS)


async def _seed_members(db, kwhs, *, month=MONTH):
    ids = []
    for i, kwh in enumerate(kwhs):
        mid = await _member(db, f"M{i}", participates=True)
        _add_consumption(db, member_id=mid, kwh=kwh, month=month, sid=f"s-{month}-{mid}")
        ids.append(mid)
    return ids


async def _preview_for(db, consumption_lines, *, month=MONTH, equal_nok=EQUAL_NOK):
    """Fresh draft with the equal line + the given ``(description, amount)``
    consumption lines, frozen; returns ``preview``."""
    repo = SettlementRepo(db)
    s = await repo.create_draft(month, actor=AuditContext.system())
    sid = int(s["id"])
    if equal_nok is not None:
        await repo.add_line(
            sid,
            description="Kapasitetsledd",
            allocation_method="equal",
            amount=Decimal(equal_nok),
            actor=AuditContext.system(),
        )
    for desc, amount in consumption_lines:
        await repo.add_line(
            sid,
            description=desc,
            allocation_method="consumption",
            amount=Decimal(amount),
            actor=AuditContext.system(),
        )
    await repo.set_invoice(sid, invoice_kwh="591.33", actor=AuditContext.system())
    await repo.add_attachment(
        sid, filename="faktura.pdf", content=b"%PDF-1.4 fake", actor=AuditContext.system()
    )
    await repo.freeze(sid, actor=AuditContext.system())
    return repo.preview(sid)


def _charges(preview):
    return [m["charge_ore"] for m in preview["members"]]


def _consumption_share(member):
    rows = [ln for ln in member["lines"] if ln["kind"] == "consumption"]
    return sum(ln["amount_ore"] for ln in rows), len(rows)


async def _charges_for(tmp_path, name, grouping, *, equal_nok=EQUAL_NOK, kwhs=KWH):
    db = _fresh_db(tmp_path, name)
    try:
        await _seed_members(db, kwhs)
        preview = await _preview_for(db, grouping, equal_nok=equal_nok)
        return preview, _charges(preview)
    finally:
        db.close()


async def test_three_groupings_give_identical_charges(tmp_path):
    six_preview, six = await _charges_for(tmp_path, "six", SIX)
    _, three = await _charges_for(tmp_path, "three", THREE)
    _, one = await _charges_for(tmp_path, "one", ONE)

    assert six == EXPECTED_TOTAL
    assert three == six
    assert one == six

    # the per-member consumption part is exactly the bucket split, applied once
    for m, want in zip(six_preview["members"], EXPECTED_CONSUMPTION, strict=True):
        assert _consumption_share(m) == (want, 1)


async def test_total_preserved_and_matches_invoice_lines(tmp_path):
    for name, grouping in (("six", SIX), ("three", THREE), ("one", ONE)):
        preview, charges = await _charges_for(tmp_path, name, grouping)
        assert sum(charges) == INVOICE_TOTAL_ORE
        assert (
            preview["total_charged_ore"] == preview["invoice_lines_total_ore"] == INVOICE_TOTAL_ORE
        )
        assert not any(w["code"] == "charge_total_mismatch" for w in preview["warnings"])


async def test_single_forbrukskostnader_row_in_breakdown(tmp_path):
    for name, grouping in (("six", SIX), ("three", THREE), ("one", ONE)):
        preview, _ = await _charges_for(tmp_path, name, grouping)

        consumption_rows = [ln for ln in preview["lines"] if ln["kind"] == "consumption"]
        assert len(consumption_rows) == 1
        row = consumption_rows[0]
        assert row["line_id"] is None
        assert row["description"] == CONSUMPTION_LINE_LABEL
        assert row["amount_ore"] == 53665
        assert row["allocated_ore"] == 53665

        for m in preview["members"]:
            assert _consumption_share(m)[1] == 1


async def test_residual_spread_by_fractional_remainder(tmp_path):
    """A bucket that does not divide evenly: 536.67 kr = 53667 øre. Floors are
    [11455, 6706, 17236, 18268] (sum 53665); the two leftover øre go one each to
    the two largest fractional remainders (M1 .90 and M2 .46), never piled onto
    one member."""
    preview, _ = await _charges_for(tmp_path, "resid", [("Forbruk", "536.67")])
    shares = [_consumption_share(m)[0] for m in preview["members"]]
    assert shares == [11455, 6707, 17237, 18268]
    assert sum(shares) == 53667
    # no member is more than one øre above its floor
    for got, floor in zip(shares, [11455, 6706, 17236, 18268], strict=True):
        assert got - floor in (0, 1)


def test_old_per_line_math_was_grouping_dependent():
    """Rationale guard, at the ``allocate_by_weights`` level: splitting each line
    on its own makes the result depend on the itemisation — which is exactly what
    pooling removes."""
    weights = [Decimal(k) for k in KWH]

    def per_line(lines):
        totals = [0, 0, 0, 0]
        for _desc, amount in lines:
            for i, s in enumerate(allocate_by_weights(nok_to_ore(Decimal(amount)), weights)):
                totals[i] += s
        return totals

    assert per_line(SIX) != per_line(ONE)
    assert per_line(SIX) == [11455, 6705, 17237, 18268]
    assert per_line(ONE) == [11455, 6706, 17236, 18268]

    bucket = allocate_by_weights(sum(nok_to_ore(Decimal(a)) for _d, a in SIX), weights)
    assert list(bucket) == per_line(ONE) == EXPECTED_CONSUMPTION


def _partition(rng: random.Random, total: int, k: int) -> list[int]:
    """``k`` non-zero integers summing to ``total`` (signs allowed)."""
    while True:
        parts = [rng.randint(-20000, 20000) for _ in range(k - 1)]
        parts.append(total - sum(parts))
        if all(p != 0 for p in parts):
            return parts


async def test_property_regrouping_is_invariant(tmp_path):
    """Random member counts, kWh vectors and random line partitions of a random
    consumption total: the engine's per-member charges match the single pooled
    line, and the total is preserved."""
    rng = random.Random(20260902)
    for it in range(25):
        n = rng.randint(3, 7)
        kwhs = [f"{rng.randint(50, 40000) / 100:.2f}" for _ in range(n)]
        total_ore = rng.randint(-500_00, 5_000_00) or 100_00
        parts = _partition(rng, total_ore, rng.randint(1, 6))
        lines = [
            (f"L{j}", str((Decimal(p) / 100).quantize(Decimal("0.01"))))
            for j, p in enumerate(parts)
        ]
        pooled_nok = str((Decimal(total_ore) / 100).quantize(Decimal("0.01")))

        _, reference = await _charges_for(
            tmp_path, f"ref{it}", [("Forbruk", pooled_nok)], equal_nok=None, kwhs=kwhs
        )
        assert sum(reference) == total_ore

        _, split = await _charges_for(tmp_path, f"split{it}", lines, equal_nok=None, kwhs=kwhs)
        assert split == reference
        assert sum(split) == total_ore
