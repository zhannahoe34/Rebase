"""Both sides add a guard at the same spot in restock(): textual conflict, resolvable by
keeping both guards (so the PR's own added lines survive unchanged; PLAN.md Q4)."""

from sandbox_gen.scenarios.base import Append, Change, Expected, Replace, Scenario, Write

_GUARD_ANCHOR = '        raise ValueError("qty must be positive")\n'

SCENARIO = Scenario(
    name="real_conflict",
    description="Textual conflict in the same function, resolvable.",
    merged=Change(
        title="Cap restock quantity",
        body="Rejects restocks above `MAX_RESTOCK` (1000 units) to catch data-entry errors.",
        ops=(
            Replace(
                "shop/inventory.py",
                '"""Stock bookkeeping."""\n',
                '"""Stock bookkeeping."""\n\nMAX_RESTOCK = 1000\n',
            ),
            Replace(
                "shop/inventory.py",
                _GUARD_ANCHOR,
                _GUARD_ANCHOR
                + "    if qty > MAX_RESTOCK:\n"
                + '        raise ValueError(f"qty must be at most {MAX_RESTOCK}")\n',
            ),
            Append(
                "tests/test_inventory.py",
                "\n\ndef test_restock_rejects_over_max():\n"
                "    with pytest.raises(ValueError):\n"
                '        restock({}, "apple", 1001)\n',
            ),
        ),
    ),
    pr=Change(
        title="Reject empty item names in restock",
        body="`restock` now raises if the item name is empty instead of creating a '' entry.",
        ops=(
            Replace(
                "shop/inventory.py",
                _GUARD_ANCHOR,
                _GUARD_ANCHOR
                + "    if not item:\n"
                + '        raise ValueError("item name required")\n',
            ),
            Write(
                "tests/test_inventory_items.py",
                "import pytest\n\n"
                "from shop.inventory import restock\n\n\n"
                "def test_restock_rejects_empty_item():\n"
                "    with pytest.raises(ValueError):\n"
                '        restock({}, "", 1)\n',
            ),
        ),
    ),
    expected=Expected("pushed", "push", "Resolver keeps both guards; tests pass."),
    expected_signals={
        "conflict_count": 1,
        "conflicted_files": ["shop/inventory.py"],
        "file_overlap": ["shop/inventory.py"],
        "symbol_overlap": ["shop/inventory.py:restock"],
        "touches": {},
    },
)
