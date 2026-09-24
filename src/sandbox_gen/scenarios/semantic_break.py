"""Main adds a required parameter to calc_price(); the PR adds a new caller using the old
signature. Applies cleanly, tests fail: the verifier must catch it (headline demo case)."""

from sandbox_gen.scenarios.base import Change, Expected, Replace, Scenario, Write

SCENARIO = Scenario(
    name="semantic_break",
    description="Signature change on main + new call with the old signature in the PR.",
    merged=Change(
        title="Include tax in calc_price",
        body="`calc_price` now takes a required `tax_rate` (e.g. 0.2 for 20%) and returns "
        "the tax-inclusive total. Existing callers and tests updated.",
        ops=(
            Replace(
                "shop/pricing.py",
                "def calc_price(base: float, qty: int) -> float:\n"
                '    """Total price for qty units at the given base price."""\n',
                "def calc_price(base: float, qty: int, tax_rate: float) -> float:\n"
                '    """Tax-inclusive total for qty units at the given base price."""\n',
            ),
            Replace(
                "shop/pricing.py",
                "    return round(base * qty, 2)\n",
                "    return round(base * qty * (1 + tax_rate), 2)\n",
            ),
            Replace(
                "tests/test_pricing.py",
                "    assert calc_price(2.5, 4) == 10.0\n",
                "    assert calc_price(2.5, 4, 0.0) == 10.0\n"
                "    assert calc_price(2.5, 4, 0.2) == 12.0\n",
            ),
            Replace(
                "tests/test_pricing.py",
                "        calc_price(1.0, -1)\n",
                "        calc_price(1.0, -1, 0.0)\n",
            ),
        ),
    ),
    pr=Change(
        title="Add cart_total",
        body="Adds `shop/cart.py` with `cart_total(items)` summing (unit_price, qty) lines.",
        ops=(
            Write(
                "shop/cart.py",
                '"""Shopping cart totals."""\n\n'
                "from shop.pricing import calc_price\n\n\n"
                "def cart_total(items: list[tuple[float, int]]) -> float:\n"
                '    """Sum of line prices for (unit_price, qty) pairs."""\n'
                "    return round(sum(calc_price(price, qty) for price, qty in items), 2)\n",
            ),
            Write(
                "tests/test_cart.py",
                "from shop.cart import cart_total\n\n\n"
                "def test_cart_total():\n"
                "    assert cart_total([(2.5, 4), (1.0, 3)]) == 13.0\n",
            ),
        ),
    ),
    expected=Expected(
        "escalated", "verifier", "Clean rebase but cart_total uses the old signature."
    ),
    expected_signals={
        "conflict_count": 0,
        "conflicted_files": [],
        "file_overlap": [],
        "symbol_overlap": [],
        "touches": {},
    },
)
