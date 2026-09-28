"""A clean PR nobody approved: the workflow must not touch it (no matrix leg, no comment),
however safe the rebase would be. Nothing else in the run may be affected by its absence."""

from sandbox_gen.scenarios.base import Change, Expected, Scenario, Write

SCENARIO = Scenario(
    name="unapproved",
    description="Safe PR with no approval and no approval label.",
    approved=False,
    merged=Change(
        title="Add a roadmap",
        body="Adds `docs/ROADMAP.md`.",
        ops=(Write("docs/ROADMAP.md", "# Roadmap\n\n- gift cards\n"),),
    ),
    pr=Change(
        title="Add a greeting helper",
        body="Adds `shop/greeting.py` with `greet(name)`.",
        ops=(
            Write(
                "shop/greeting.py",
                '"""Greetings."""\n\n\ndef greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
            ),
            Write(
                "tests/test_greeting.py",
                "from shop.greeting import greet\n\n\n"
                "def test_greet():\n"
                '    assert greet("Ann") == "Hello, Ann!"\n',
            ),
        ),
    ),
    expected=Expected(
        "skipped", "eligibility", "Not approved: excluded from the matrix, no comment."
    ),
    expected_signals={
        "conflict_count": 0,
        "conflicted_files": [],
        "file_overlap": [],
        "symbol_overlap": [],
        "touches": {},
    },
)
