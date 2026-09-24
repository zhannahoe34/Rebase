"""Analyst agent (D4): summarize the intent of one change via BAML."""

from rebase_agent import llm
from rebase_agent.ledger import Ledger
from rebase_agent.models import PRSummary, Usage

# Refuse rather than silently truncate (never drop part of a diff the analyst should see).
MAX_DIFF_CHARS = 200_000


def summarize_change(
    diff: str,
    title: str,
    body: str,
    *,
    model: str,
    stage: str = "analyst_pr",
    ledger: Ledger | None = None,
    pr: str | None = None,
) -> tuple[PRSummary, Usage]:
    if len(diff) > MAX_DIFF_CHARS:
        raise ValueError(f"diff is {len(diff)} chars (> {MAX_DIFF_CHARS}); not truncating")
    result, usage = llm.call(
        "SummarizeChange",
        {"title": title, "body": body, "diff": diff},
        model=model,
        stage=stage,
        ledger=ledger,
        pr=pr,
    )
    return PRSummary.model_validate(result.model_dump()), usage
