"""Orchestrator (D5): signals + two summaries -> Decision, via BAML. No repo access."""

from rebase_agent import llm
from rebase_agent.baml_client import types as bt
from rebase_agent.ledger import Ledger
from rebase_agent.models import Decision, PRSummary, Signals, Usage


def decide(
    signals: Signals,
    merged: PRSummary,
    pr: PRSummary,
    *,
    model: str,
    ledger: Ledger | None = None,
    pr_ref: str | None = None,
) -> tuple[Decision, Usage]:
    result, usage = llm.call(
        "DecideRebase",
        {
            "signals": bt.Signals.model_validate(signals.model_dump()),
            "merged": bt.PRSummary.model_validate(merged.model_dump()),
            "pr": bt.PRSummary.model_validate(pr.model_dump()),
        },
        model=model,
        stage="orchestrator",
        ledger=ledger,
        pr=pr_ref,
    )
    return Decision.model_validate(result.model_dump()), usage
