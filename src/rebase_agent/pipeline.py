"""Per-PR decision pipeline (PLAN.md §0.5, up to combine). Phase 3 adds resolve/verify/push.

The merged-change summary is computed once per run and reused for every PR (D4).
"""

from pathlib import Path

from rebase_agent import analysts, config, orchestrator
from rebase_agent.git_ops import commit_message, full_diff, merge_base, rev_parse
from rebase_agent.ledger import Ledger
from rebase_agent.models import FinalDecision, PRSummary
from rebase_agent.policy import apply_policy, combine
from rebase_agent.signals import compute_signals


def summarize_merged(repo: Path, base: str, merged: str, *, ledger: Ledger | None) -> PRSummary:
    """Summary of the merged change base..merged, titled by merged's commit message."""
    title, body = commit_message(repo, merged)
    summary, _ = analysts.summarize_change(
        full_diff(repo, base, merged),
        title,
        body,
        model=config.model_for("analyst"),
        stage="analyst_merged",
        ledger=ledger,
    )
    return summary


def decide_pr(
    repo: Path,
    base: str,
    merged: str,
    pr_branch: str,
    merged_summary: PRSummary,
    *,
    ledger: Ledger | None,
) -> FinalDecision:
    signals = compute_signals(repo, base, merged, pr_branch)
    pr_base = merge_base(repo, rev_parse(repo, base), rev_parse(repo, pr_branch))
    title, body = commit_message(repo, pr_branch)
    pr_summary, _ = analysts.summarize_change(
        full_diff(repo, pr_base, pr_branch),
        title,
        body,
        model=config.model_for("analyst"),
        stage="analyst_pr",
        ledger=ledger,
        pr=pr_branch,
    )
    decision, _ = orchestrator.decide(
        signals,
        merged_summary,
        pr_summary,
        model=config.model_for("orchestrator"),
        ledger=ledger,
        pr_ref=pr_branch,
    )
    return combine(decision, apply_policy(signals))


def decide_all(
    repo: Path,
    base: str,
    merged: str,
    pr_branches: list[str],
    *,
    ledger: Ledger | None,
    merged_summary: PRSummary | None = None,
) -> dict[str, FinalDecision]:
    """Decide every PR, summarizing the merged change at most once."""
    if merged_summary is None:
        merged_summary = summarize_merged(repo, base, merged, ledger=ledger)
    return {
        pr: decide_pr(repo, base, merged, pr, merged_summary, ledger=ledger) for pr in pr_branches
    }
