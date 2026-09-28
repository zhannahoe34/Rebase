"""The PR (not main) touches an auth module: policy must escalate even though the change
is purely additive and rebases cleanly (the orchestrator is expected to say auto_rebase)."""

from sandbox_gen.scenarios.base import Append, Change, Expected, Scenario, Write

SCENARIO = Scenario(
    name="auth_touch",
    description="PR adds to shop/auth/; main change is unrelated.",
    merged=Change(
        title="Add a version module",
        body="Adds `shop/version.py` with `__version__`.",
        ops=(Write("shop/version.py", '"""Package version."""\n\n__version__ = "0.2.0"\n'),),
    ),
    pr=Change(
        title="Add token expiry check",
        body="Adds `expired(issued_at, now, ttl)` to the auth tokens module.",
        ops=(
            Append(
                "shop/auth/tokens.py",
                "\n\ndef expired(issued_at: float, now: float, ttl: float = 3600.0) -> bool:\n"
                '    """True once a token is older than ttl seconds."""\n'
                "    return now - issued_at > ttl\n",
            ),
            Write(
                "tests/test_auth_expiry.py",
                "from shop.auth.tokens import expired\n\n\n"
                "def test_expired():\n"
                "    assert not expired(0.0, 10.0)\n"
                "    assert expired(0.0, 4000.0)\n",
            ),
        ),
    ),
    expected=Expected("escalated", "policy", "Auth path touched by the PR."),
    expected_signals={
        "conflict_count": 0,
        "conflicted_files": [],
        "file_overlap": [],
        "symbol_overlap": [],
        "touches": {"auth": {"pr": ["shop/auth/tokens.py", "tests/test_auth_expiry.py"]}},
    },
)
