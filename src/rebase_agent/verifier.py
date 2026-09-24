"""Verifier (D8): rerun the tests on the rebased branch, then check the PR's intent survived.

verdict = "pass" only if the tests pass AND the intent is preserved. Catching rebases
that apply cleanly but are semantically broken is its most important job.
"""

from pathlib import Path

from rebase_agent import llm
from rebase_agent.baml_client import types as bt
from rebase_agent.git_ops import full_diff
from rebase_agent.ledger import Ledger
from rebase_agent.models import PRSummary, VerifierResult
from rebase_agent.resolver.tools import run_pytest


def verify(
    workdir: Path,
    base: str,
    pr: PRSummary,
    *,
    model: str,
    ledger: Ledger | None = None,
    pr_ref: str | None = None,
) -> VerifierResult:
    """`base` is the new main the PR was rebased onto; the PR diff is base..HEAD."""
    tests_passed, tail = run_pytest(Path(workdir))
    check, _ = llm.call(
        "CheckIntent",
        {
            "pr": bt.PRSummary.model_validate(pr.model_dump()),
            "resolved_diff": full_diff(Path(workdir), base, "HEAD"),
        },
        model=model,
        stage="verifier_intent",
        ledger=ledger,
        pr=pr_ref,
    )
    return VerifierResult(
        tests_passed=tests_passed,
        test_output_tail=tail,
        intent_preserved=check.intent_preserved,
        intent_reasons=list(check.reasons),
        verdict="pass" if tests_passed and check.intent_preserved else "escalate",
    )
