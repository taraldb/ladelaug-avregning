"""Money helpers. The canonical stored unit is an integer number of øre; a
companion exact ``Decimal`` string is kept alongside it in the ledger. All
rounding is banker's rounding (``ROUND_HALF_EVEN``). Never construct a
``Decimal`` directly from a ``float`` — always go through ``str`` first.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

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
