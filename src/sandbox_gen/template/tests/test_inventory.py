import pytest
from shop.inventory import reserve, restock


def test_restock_adds():
    assert restock({"apple": 1}, "apple", 2) == {"apple": 3}


def test_restock_rejects_non_positive():
    with pytest.raises(ValueError):
        restock({}, "apple", 0)


def test_reserve_removes():
    assert reserve({"apple": 3}, "apple", 2) == {"apple": 1}


def test_reserve_rejects_oversell():
    with pytest.raises(ValueError):
        reserve({"apple": 1}, "apple", 2)
