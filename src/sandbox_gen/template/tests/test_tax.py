from shop.tax import tax_for


def test_tax_for_known_and_unknown_regions():
    assert tax_for("EU") == 0.2
    assert tax_for("nowhere") == 0.0
