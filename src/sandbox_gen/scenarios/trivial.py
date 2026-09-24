"""Merged change and PR touch different files: should auto-rebase and push."""

from sandbox_gen.scenarios.base import Append, Change, Expected, Replace, Scenario

SCENARIO = Scenario(
    name="trivial",
    description="Non-overlapping files.",
    merged=Change(
        title="Add low_stock helper to inventory",
        body="Adds `low_stock(stock, threshold)` listing items at or below a threshold.",
        ops=(
            Append(
                "shop/inventory.py",
                "\n\ndef low_stock(stock: dict[str, int], threshold: int) -> list[str]:\n"
                '    """Items with at most threshold units, sorted by name."""\n'
                "    return sorted(item for item, qty in stock.items() if qty <= threshold)\n",
            ),
            Replace(
                "tests/test_inventory.py",
                "from shop.inventory import reserve, restock",
                "from shop.inventory import low_stock, reserve, restock",
            ),
            Append(
                "tests/test_inventory.py",
                "\n\ndef test_low_stock():\n"
                '    assert low_stock({"apple": 1, "pear": 5, "fig": 0}, 1) == ["apple", "fig"]\n',
            ),
        ),
    ),
    pr=Change(
        title="Add currency formatting to reports",
        body="Adds `format_currency(amount)` for report output, e.g. `$1,234.50`.",
        ops=(
            Append(
                "shop/report.py",
                '\n\ndef format_currency(amount: float) -> str:\n    return f"${amount:,.2f}"\n',
            ),
            Replace(
                "tests/test_report.py",
                "from shop.report import stock_report",
                "from shop.report import format_currency, stock_report",
            ),
            Append(
                "tests/test_report.py",
                "\n\ndef test_format_currency():\n"
                '    assert format_currency(1234.5) == "$1,234.50"\n',
            ),
        ),
    ),
    expected=Expected("pushed", "push", "Clean rebase, tests pass, patch unchanged."),
    expected_signals={
        "conflict_count": 0,
        "conflicted_files": [],
        "file_overlap": [],
        "symbol_overlap": [],
        "touches": {},
    },
)
