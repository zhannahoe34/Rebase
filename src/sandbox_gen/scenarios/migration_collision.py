"""Both sides add migration 0003: policy must escalate without calling the resolver."""

from sandbox_gen.scenarios.base import Change, Expected, Scenario, Write

SCENARIO = Scenario(
    name="migration_collision",
    description="Both sides add a migration with the same number.",
    merged=Change(
        title="Add coupons table",
        body="Migration 0003 adds a `coupons` table.",
        ops=(
            Write(
                "migrations/0003_add_coupons.sql",
                "CREATE TABLE coupons (code TEXT PRIMARY KEY, pct REAL NOT NULL);\n",
            ),
        ),
    ),
    pr=Change(
        title="Add wishlist table",
        body="Migration 0003 adds a `wishlist` table.",
        ops=(
            Write(
                "migrations/0003_add_wishlist.sql",
                "CREATE TABLE wishlist (user TEXT NOT NULL, product_id INTEGER "
                "REFERENCES products(id));\n",
            ),
        ),
    ),
    expected=Expected("escalated", "policy", "Migration touched on both sides."),
    expected_signals={
        "conflict_count": 0,
        "conflicted_files": [],
        "file_overlap": [],
        "symbol_overlap": [],
        "touches": {
            "migration": {
                "merged": ["migrations/0003_add_coupons.sql"],
                "pr": ["migrations/0003_add_wishlist.sql"],
            },
        },
    },
)
