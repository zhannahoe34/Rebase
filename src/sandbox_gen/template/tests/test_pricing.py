import pytest
from shop.pricing import apply_discount, calc_price


def test_calc_price():
    assert calc_price(2.5, 4) == 10.0


def test_calc_price_rejects_negative_qty():
    with pytest.raises(ValueError):
        calc_price(1.0, -1)


def test_apply_discount():
    assert apply_discount(100.0, 25) == 75.0
