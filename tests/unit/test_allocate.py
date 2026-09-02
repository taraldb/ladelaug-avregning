from __future__ import annotations

import random
from decimal import Decimal

import pytest

from ladelaug_avregning.money import allocate_by_weights


def test_equal_split_spreads_residual_one_ore_each():
    # US-610: leftover øre from flooring are handed out one per entry; with
    # equal weights (equal remainders) that is the first entries in order.
    assert allocate_by_weights(100, [1, 1, 1]) == [34, 33, 33]
    assert allocate_by_weights(10, [1, 1, 1, 1]) == [3, 3, 2, 2]


def test_exact_division_has_no_residual():
    assert allocate_by_weights(300, [1, 1, 1]) == [100, 100, 100]


def test_weighted_by_consumption():
    # 1000 øre split by kWh 1:2:1  -> 250 : 500 : 250
    out = allocate_by_weights(1000, [Decimal(1), Decimal(2), Decimal(1)])
    assert out == [250, 500, 250]
    assert sum(out) == 1000


def test_residual_goes_to_largest_remainder():
    out = allocate_by_weights(100, [Decimal(10), Decimal(11), Decimal(9)])
    assert sum(out) == 100
    # 30 total weight -> 33.33, 36.67, 30.0 -> floors 33, 36, 30 = 99;
    # the 1 leftover øre goes to the largest fractional remainder (idx 1, .67)
    assert out == [33, 37, 30]


def test_residual_spread_never_moves_an_entry_more_than_one_ore():
    # 100 øre by 100:1:1:1:1 -> exact 96.15 / 0.96 * 4; floors 96,0,0,0,0 = 96;
    # 4 leftover øre go one each to the four small entries (remainder .96),
    # NOT all piled on the big one.
    out = allocate_by_weights(100, [Decimal(100), Decimal(1), Decimal(1), Decimal(1), Decimal(1)])
    assert out == [96, 1, 1, 1, 1]
    assert sum(out) == 100


def test_single_entry_takes_everything():
    assert allocate_by_weights(4211, [Decimal("7.5")]) == [4211]


def test_all_zero_weights_falls_back_to_even():
    assert allocate_by_weights(7, [Decimal(0), Decimal(0), Decimal(0)]) == [3, 2, 2]


def test_empty():
    assert allocate_by_weights(500, []) == []


def test_negative_weight_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        allocate_by_weights(100, [Decimal(1), Decimal(-1)])


def test_property_sum_is_preserved_over_random_cases():
    rng = random.Random(20260830)
    for _ in range(2000):
        n = rng.randint(1, 12)
        total = rng.randint(0, 5_000_00)
        weights = [Decimal(rng.randint(0, 5000)) / 100 for _ in range(n)]
        out = allocate_by_weights(total, weights)
        assert len(out) == n
        assert sum(out) == total
        assert all(isinstance(x, int) for x in out)
