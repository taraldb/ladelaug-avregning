"""Money helpers. The canonical stored unit is an integer number of øre; a
companion exact ``Decimal`` string is kept alongside it in the ledger. All
rounding is banker's rounding (``ROUND_HALF_EVEN``). Never construct a
``Decimal`` directly from a ``float`` — always go through ``str`` first.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_FLOOR, ROUND_HALF_EVEN, Decimal

_CENTS = Decimal("0.01")
_ONE = Decimal(1)


def normalise_decimal_input(raw: str) -> str:
    """Normalise a human-typed decimal string to a plain ``Decimal``-parseable
    form: accept both ``"123,45"`` and ``"123.45"`` as 123.45, and tolerate
    thousands separators (``"1 234,56"`` / ``"1.234,56"`` / ``"1,234.56"``).

    Rule: strip all whitespace; when both ``,`` and ``.`` appear, whichever comes
    last is the decimal point and the other is a grouping separator; a lone
    ``,`` is a decimal point; repeated ``,`` with no ``.`` are grouping.
    """
    s = "".join(raw.split())
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif s.count(",") == 1:
        s = s.replace(",", ".")
    elif s.count(",") > 1:
        s = s.replace(",", "")
    return s


def parse_nok(raw: str | int | Decimal) -> Decimal:
    """Parse an amount in NOK to a 2-decimal ``Decimal``. Accepts ``str``
    (comma or period decimal separator), ``int``, ``Decimal`` (and ``float``,
    routed through ``str`` so no binary float artefact leaks in). Rejects
    NaN / infinity."""
    if isinstance(raw, str):
        raw = normalise_decimal_input(raw)
    value = Decimal(str(raw))
    if not value.is_finite():
        raise ValueError(f"amount is not a finite number: {raw!r}")
    return value.quantize(_CENTS, rounding=ROUND_HALF_EVEN)


def nok_to_ore(amount: Decimal) -> int:
    """Convert a NOK ``Decimal`` to signed integer øre."""
    ore = (amount * 100).quantize(_ONE, rounding=ROUND_HALF_EVEN)
    return int(ore)


def ore_to_nok(ore: int) -> Decimal:
    """Convert signed integer øre back to a 2-decimal NOK ``Decimal``."""
    return (Decimal(ore) / 100).quantize(_CENTS, rounding=ROUND_HALF_EVEN)


def allocate_by_weights(total_ore: int, weights: Sequence[Decimal | int]) -> list[int]:
    """Split ``total_ore`` across ``weights`` into whole øre that sum exactly to
    ``total_ore`` (US-610).

    Largest-remainder apportionment: each entry starts at the floored exact
    rational ``total_ore * wᵢ / Σw``. Flooring always undershoots, leaving
    ``0 … len(weights) - 1`` øre over; those are handed out **one per entry** to
    the entries whose exact share was furthest above its floor (largest
    fractional remainder), ties broken by larger weight then lower index. No
    entry is ever moved more than one øre off its exact share. With equal weights
    this is an even split with the leftover øre on the first entries. Weights must
    be non-negative; an all-zero weight vector falls back to an even split.
    """
    n = len(weights)
    if n == 0:
        return []
    if any(w < 0 for w in weights):
        raise ValueError("weights must be non-negative")

    wsum = sum((Decimal(w) for w in weights), Decimal(0))
    if wsum <= 0:
        base, rem = divmod(total_ore, n)
        return [base + (1 if i < rem else 0) for i in range(n)]

    exact = [Decimal(total_ore) * Decimal(w) / wsum for w in weights]
    shares = [int(e.to_integral_value(rounding=ROUND_FLOOR)) for e in exact]
    residual = total_ore - sum(shares)  # always 0 .. n-1
    order = sorted(
        range(n),
        key=lambda i: (exact[i] - shares[i], Decimal(weights[i]), -i),
        reverse=True,
    )
    for i in order[:residual]:
        shares[i] += 1
    return shares
