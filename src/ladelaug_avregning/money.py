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


def parse_nok(raw: str | int | Decimal) -> Decimal:
    """Parse an amount in NOK to a 2-decimal ``Decimal``. Accepts ``str``,
    ``int``, ``Decimal`` (and ``float``, routed through ``str`` so no binary
    float artefact leaks in). Rejects NaN / infinity."""
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

    Each share is the floored exact rational ``total_ore * wᵢ / Σw``; the
    leftover øre (at most ``len(weights) - 1``) all goes to the entry with the
    largest weight, ties broken by lowest index. With equal weights this is an
    even split with the remainder on the first entry. Weights must be
    non-negative; an all-zero weight vector falls back to an even split.
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

    shares = [
        int((Decimal(total_ore) * Decimal(w) / wsum).to_integral_value(rounding=ROUND_FLOOR))
        for w in weights
    ]
    residual = total_ore - sum(shares)
    target = max(range(n), key=lambda i: (Decimal(weights[i]), -i))
    shares[target] += residual
    return shares
