"""Both sides rewrite the oversell branch of reserve() with incompatible intent: main
stops raising (partial fulfilment), the PR keeps raising with a better message. Git can't
merge it and neither can a resolver without a product decision: nothing may be pushed."""

from sandbox_gen.scenarios.base import Change, Expected, Replace, Scenario, Write

_OVERSELL = (
    "    if qty > available:\n"
    '        raise ValueError(f"only {available} {item} left")\n'
    "    stock[item] = available - qty\n"
)
_OVERSELL_TEST = (
    "def test_reserve_rejects_oversell():\n"
    "    with pytest.raises(ValueError):\n"
    '        reserve({"apple": 1}, "apple", 2)\n'
)

SCENARIO = Scenario(
    name="conflicting_intent",
    description="Same lines rewritten with contradictory behaviour.",
    merged=Change(
        title="Fulfil what is in stock when reserving too much",
        body="`reserve` no longer raises when qty exceeds stock: it takes whatever is "
        "available and leaves the item at zero, so partial orders can go ahead.",
        ops=(
            Replace(
                "shop/inventory.py",
                _OVERSELL,
                "    taken = min(qty, available)\n    stock[item] = available - taken\n",
            ),
            Replace(
                "tests/test_inventory.py",
                _OVERSELL_TEST,
                "def test_reserve_takes_what_is_left():\n"
                '    assert reserve({"apple": 1}, "apple", 2) == {"apple": 0}\n',
            ),
        ),
    ),
    pr=Change(
        title="Say how short we are when reserve fails",
        body="`reserve` still refuses to oversell, and the error now reports the shortfall "
        "(`short by N`) so order screens can show it.",
        ops=(
            Replace(
                "shop/inventory.py",
                _OVERSELL,
                "    if qty > available:\n"
                '        raise ValueError(f"short by {qty - available} {item}")\n'
                "    stock[item] = available - qty\n",
            ),
            Write(
                "tests/test_reserve_shortfall.py",
                "import pytest\n\n"
                "from shop.inventory import reserve\n\n\n"
                "def test_reserve_reports_shortfall():\n"
                '    with pytest.raises(ValueError, match="short by 1"):\n'
                '        reserve({"apple": 1}, "apple", 2)\n',
            ),
        ),
    ),
    expected=Expected(
        "escalated",
        "orchestrator",
        "Contradictory intent: a keep-both resolution can't satisfy both. Never pushed.",
        also_stages=("resolver", "verifier"),
    ),
    expected_signals={
        "conflict_count": 1,
        "conflicted_files": ["shop/inventory.py"],
        "file_overlap": ["shop/inventory.py"],
        "symbol_overlap": ["shop/inventory.py:reserve"],
        "touches": {},
    },
)
