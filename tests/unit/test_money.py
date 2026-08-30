from decimal import Decimal

import pytest

from ladelaug_avregning.money import nok_to_ore, ore_to_nok, parse_nok


@pytest.mark.parametrize(
    "value",
    ["0.00", "100.00", "1500.50", "-50.00", "0.01", "-0.01", "999999.99"],
)
def test_round_trip(value):
    d = Decimal(value)
    assert ore_to_nok(nok_to_ore(d)) == d


def test_nok_to_ore_negative():
    assert nok_to_ore(Decimal("-50.00")) == -5000


def test_half_even_rounding_on_sub_ore():
    # 1.005 -> 100.5 øre -> banker's rounding to even -> 100
    assert nok_to_ore(Decimal("1.005")) == 100
    # 1.015 -> 101.5 øre -> rounds to even -> 102
    assert nok_to_ore(Decimal("1.015")) == 102


def test_parse_nok_quantizes_half_even():
    assert parse_nok("158.485") == Decimal("158.48")
    assert parse_nok("158.495") == Decimal("158.50")


def test_parse_nok_accepts_float_via_str():
    assert parse_nok(0.1) == Decimal("0.10")


def test_parse_nok_rejects_non_finite():
    with pytest.raises(ValueError):
        parse_nok("nan")
    with pytest.raises(ValueError):
        parse_nok("inf")
