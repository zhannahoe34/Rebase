"""Main changes what apply_discount()'s argument means without touching its signature; the
PR adds a caller written for the old meaning. Rebases cleanly, tests fail. A subtler
semantic break than semantic_break: no signature change for a reviewer to spot."""

from sandbox_gen.scenarios.base import Change, Expected, Replace, Scenario, Write

SCENARIO = Scenario(
    name="behavior_change",
    description="Same signature, different meaning; new caller assumes the old one.",
    merged=Change(
        title="Express discounts as a fraction",
        body="`apply_discount(price, pct)` now takes `pct` as a fraction between 0 and 1 "
        "(0.25 = 25% off) instead of a percentage between 0 and 100.",
        ops=(
            Replace(
                "shop/pricing.py",
                '    """Apply a percentage discount (0-100)."""\n'
                "    if not 0 <= pct <= 100:\n"
                '        raise ValueError("pct must be between 0 and 100")\n'
                "    return round(price * (1 - pct / 100), 2)\n",
                '    """Apply a discount given as a fraction (0-1)."""\n'
                "    if not 0 <= pct <= 1:\n"
                '        raise ValueError("pct must be between 0 and 1")\n'
                "    return round(price * (1 - pct), 2)\n",
            ),
            Replace(
                "tests/test_pricing.py",
                "    assert apply_discount(100.0, 25) == 75.0\n",
                "    assert apply_discount(100.0, 0.25) == 75.0\n",
            ),
        ),
    ),
    pr=Change(
        title="Add a 10% promo price",
        body="Adds `shop/promo.py` with `promo_price(price)`, which takes 10% off using "
        "`apply_discount`.",
        ops=(
            Write(
                "shop/promo.py",
                '"""Promotions."""\n\n'
                "from shop.pricing import apply_discount\n\n\n"
                "def promo_price(price: float) -> float:\n"
                '    """Price after the standing 10% promotion."""\n'
                "    return apply_discount(price, 10)\n",
            ),
            Write(
                "tests/test_promo.py",
                "from shop.promo import promo_price\n\n\n"
                "def test_promo_price():\n"
                "    assert promo_price(50.0) == 45.0\n",
            ),
        ),
    ),
    expected=Expected(
        "escalated",
        "orchestrator",
        "Clean rebase but promo_price passes 10 where a fraction is now required. If the "
        "orchestrator lets it through, the verifier must catch it.",
        also_stages=("verifier",),
    ),
    expected_signals={
        "conflict_count": 0,
        "conflicted_files": [],
        "file_overlap": [],
        "symbol_overlap": [],
        "touches": {},
    },
)
