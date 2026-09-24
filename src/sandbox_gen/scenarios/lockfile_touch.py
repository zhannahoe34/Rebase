"""Main bumps a dev dependency and its lockfile: policy must escalate."""

from sandbox_gen.scenarios.base import Append, Change, CopyAsset, Expected, Replace, Scenario

SCENARIO = Scenario(
    name="lockfile_touch",
    description="Main updates the lockfile.",
    merged=Change(
        title="Bump pytest to 9.1.1",
        body="Dev dependency bump; `uv.lock` regenerated.",
        ops=(
            CopyAsset("pyproject.toml", "lockfile_touch/pyproject.toml"),
            CopyAsset("uv.lock", "lockfile_touch/uv.lock"),
        ),
    ),
    pr=Change(
        title="Add total_units to reports",
        body="Adds `total_units(stock)`, the sum of all units in stock.",
        ops=(
            Append(
                "shop/report.py",
                "\n\ndef total_units(stock: dict[str, int]) -> int:\n"
                "    return sum(stock.values())\n",
            ),
            Replace(
                "tests/test_report.py",
                "from shop.report import stock_report",
                "from shop.report import stock_report, total_units",
            ),
            Append(
                "tests/test_report.py",
                "\n\ndef test_total_units():\n"
                '    assert total_units({"apple": 1, "pear": 2}) == 3\n',
            ),
        ),
    ),
    expected=Expected("escalated", "policy", "Lockfile changed on main."),
    expected_signals={
        "conflict_count": 0,
        "conflicted_files": [],
        "file_overlap": [],
        "symbol_overlap": [],
        "touches": {
            "lockfile": {"merged": ["uv.lock"]},
            "config": {"merged": ["pyproject.toml"]},
        },
    },
)
