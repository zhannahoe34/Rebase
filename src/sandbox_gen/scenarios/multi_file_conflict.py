"""Two conflicts in two files, each resolvable by keeping both sides: the resolver must
work through several files and the PR's own added lines must survive unchanged (Q4)."""

from sandbox_gen.scenarios.base import Change, Expected, Replace, Scenario, Write

_SHIPPING_ANCHOR = '    """Flat fee plus a per-kilo rate."""\n'
_TAX_ANCHOR = '        "EU": 0.2,\n'

SCENARIO = Scenario(
    name="multi_file_conflict",
    description="Conflicts in two files, both resolvable.",
    merged=Change(
        title="Validate shipping weight and add UK tax",
        body="`shipping_cost` rejects non-positive weights; `tax_for` knows the UK (20%).",
        ops=(
            Replace(
                "shop/shipping.py",
                _SHIPPING_ANCHOR,
                _SHIPPING_ANCHOR
                + "    if weight_kg <= 0:\n"
                + '        raise ValueError("weight must be positive")\n',
            ),
            Replace("shop/tax.py", _TAX_ANCHOR, _TAX_ANCHOR + '        "UK": 0.2,\n'),
            Write(
                "tests/test_shipping_weight.py",
                "import pytest\n\n"
                "from shop.shipping import shipping_cost\n\n\n"
                "def test_shipping_rejects_non_positive_weight():\n"
                "    with pytest.raises(ValueError):\n"
                "        shipping_cost(0)\n",
            ),
            Write(
                "tests/test_tax_uk.py",
                "from shop.tax import tax_for\n\n\n"
                "def test_uk_rate():\n"
                '    assert tax_for("UK") == 0.2\n',
            ),
        ),
    ),
    pr=Change(
        title="Cap shipping weight and add Canadian tax",
        body="`shipping_cost` rejects parcels over 50 kg; `tax_for` knows Canada (5%).",
        ops=(
            Replace(
                "shop/shipping.py",
                _SHIPPING_ANCHOR,
                _SHIPPING_ANCHOR
                + "    if weight_kg > 50:\n"
                + '        raise ValueError("parcel too heavy")\n',
            ),
            Replace("shop/tax.py", _TAX_ANCHOR, _TAX_ANCHOR + '        "CA": 0.05,\n'),
            Write(
                "tests/test_shipping_cap.py",
                "import pytest\n\n"
                "from shop.shipping import shipping_cost\n\n\n"
                "def test_shipping_rejects_heavy_parcels():\n"
                "    with pytest.raises(ValueError):\n"
                "        shipping_cost(51)\n",
            ),
            Write(
                "tests/test_tax_ca.py",
                "from shop.tax import tax_for\n\n\n"
                "def test_canada_rate():\n"
                '    assert tax_for("CA") == 0.05\n',
            ),
        ),
    ),
    expected=Expected("pushed", "push", "Resolver keeps both sides in both files; tests pass."),
    expected_signals={
        "conflict_count": 2,
        "conflicted_files": ["shop/shipping.py", "shop/tax.py"],
        "file_overlap": ["shop/shipping.py", "shop/tax.py"],
        "symbol_overlap": ["shop/shipping.py:shipping_cost", "shop/tax.py:tax_for"],
        "touches": {},
    },
)
