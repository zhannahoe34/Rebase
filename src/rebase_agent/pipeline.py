"""Per-PR pipeline (PLAN.md §0.5).

`decide_pr` stops at the decision. `run_pr` goes on: throwaway clone, rebase, resolver
(only if the rebase conflicts), verifier, stale check, then push (or "would push").
The merged-change summary is computed once per run and reused for every PR (D4).
"""

import os
import time
from pathlib import Path

import anyio

from rebase_agent import analysts, config, orchestrator
from rebase_agent.git_ops import commit_message, full_diff, merge_base, rev_parse
from rebase_agent.github_api import PushRejected, PushTarget
from rebase_agent.github_api import push as git_push
from rebase_agent.ledger import Ledger, read_rows
from rebase_agent.models import (
    CostBreakdown,
    Decision,
    FinalDecision,
    PRSummary,
    RunOutcome,
    Signals,
)
from rebase_agent.policy import apply_policy, combine
from rebase_agent.resolver.agent import cleanup, prepare_workdir, resolve
from rebase_agent.signals import compute_signals
from rebase_agent.stale import stale_check
from rebase_agent.verifier import verify


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


def summarize_pr(repo: Path, base: str, pr_branch: str, *, ledger: Ledger | None) -> PRSummary:
    pr_base = merge_base(repo, rev_parse(repo, base), rev_parse(repo, pr_branch))
    title, body = commit_message(repo, pr_branch)
    summary, _ = analysts.summarize_change(
        full_diff(repo, pr_base, pr_branch),
        title,
        body,
        model=config.model_for("analyst"),
        stage="analyst_pr",
        ledger=ledger,
        pr=pr_branch,
    )
    return summary


def _decide(
    signals: Signals,
    merged_summary: PRSummary,
    pr_summary: PRSummary,
    *,
    ledger: Ledger | None,
    pr_branch: str,
    force_resolve: bool = False,
) -> FinalDecision:
    policy = apply_policy(signals)
    if force_resolve:
        # Q3: skip the orchestrator (not the policy) to exercise the resolver/verifier path.
        skipped = Decision(
            action="auto_rebase", confidence=1.0, reasons=["--force-resolve: orchestrator skipped"]
        )
        return combine(skipped, policy, confidence_floor=0.0)
    decision, _ = orchestrator.decide(
        signals,
        merged_summary,
        pr_summary,
        model=config.model_for("orchestrator"),
        ledger=ledger,
        pr_ref=pr_branch,
    )
    return combine(decision, policy)


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
    pr_summary = summarize_pr(repo, base, pr_branch, ledger=ledger)
    return _decide(signals, merged_summary, pr_summary, ledger=ledger, pr_branch=pr_branch)


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


def _cost(ledger: Ledger, pr_branch: str, first_row: int) -> CostBreakdown:
    """Rows this run_pr call wrote for the PR, plus the run's shared merged-summary rows
    (pr=None, same scenario), shown in full: its per-PR share is in `rebase-agent costs`."""
    rows = read_rows(ledger.run_dir)
    mine = [r for r in rows[first_row:] if r.pr == pr_branch]
    shared = [r for r in rows if r.pr is None and r.scenario == ledger.scenario]
    per_stage: dict[str, float] = {}
    for row in shared + mine:
        per_stage[row.stage] = per_stage.get(row.stage, 0.0) + row.cost_usd
    return CostBreakdown(per_stage_usd=per_stage, total_usd=sum(per_stage.values()))


def run_pr(
    repo: Path,
    base: str,
    merged: str,
    pr_branch: str,
    merged_summary: PRSummary,
    *,
    ledger: Ledger,
    pr_number: int | None = None,
    force_resolve: bool = False,
    push: PushTarget | None = None,
) -> RunOutcome:
    """Every outcome, including errors, comes back as a RunOutcome (never raises).

    Without `push` it's a dry run ("would push"). With it, the rebased branch is pushed
    with --force-with-lease only after the verifier and stale check pass.
    """
    start = time.monotonic()
    first_row = len(read_rows(ledger.run_dir))
    out: dict = {
        "pr_number": pr_number,
        "pr_branch": pr_branch,
        "dry_run": push is None,
        "signals": None,
        "merged_summary": merged_summary,
        "pr_summary": None,
        "decision": None,
    }
    stage = "signals"
    workdir: Path | None = None

    def done(final: str, stage: str, error: str | None = None) -> RunOutcome:
        return RunOutcome(
            **out,
            final=final,
            stage=stage,
            error=error,
            cost=_cost(ledger, pr_branch, first_row),
            latency_s=round(time.monotonic() - start, 1),
        )

    try:
        out["signals"] = compute_signals(repo, base, merged, pr_branch)
        stage = "analyst_pr"
        out["pr_summary"] = summarize_pr(repo, base, pr_branch, ledger=ledger)
        stage = "orchestrator"
        decision = _decide(
            out["signals"],
            merged_summary,
            out["pr_summary"],
            ledger=ledger,
            pr_branch=pr_branch,
            force_resolve=force_resolve,
        )
        out["decision"] = decision
        if decision.action == "escalate":
            return done("escalated", "policy" if "policy" in decision.escalated_by else stage)

        stage = "resolver"
        workdir, onto, head = prepare_workdir(repo, merged, pr_branch)
        if push is not None and head != push.expected_sha:
            return done(
                "escalated", stage, f"PR head moved: {head[:12]} != {push.expected_sha[:12]}"
            )
        resolved = anyio.run(
            lambda: resolve(
                workdir,
                onto,
                out["pr_summary"],
                config.resolver_caps(),
                model=config.model_for("resolver"),
                ledger=ledger,
                pr_ref=pr_branch,
            )
        )
        out["resolver"] = resolved
        if resolved.status == "error":
            return done("error", stage, resolved.reason)
        if resolved.status == "escalated":
            return done("escalated", stage)

        stage = "verifier"
        verdict = verify(
            workdir,
            onto,
            out["pr_summary"],
            model=config.model_for("verifier"),
            ledger=ledger,
            pr_ref=pr_branch,
        )
        out["verifier"] = verdict
        if verdict.verdict == "escalate":
            return done("escalated", stage)

        stage = "stale"
        old_base = merge_base(workdir, onto, head)
        out["stale"] = stale_check(workdir, old_base, head, onto, "HEAD")
        if not out["stale"].unchanged:
            return done("escalated", stage)

        stage = "push"
        if push is not None:
            try:
                git_push(workdir, push)
            except PushRejected as e:
                return done("escalated", stage, str(e))
        return done("pushed", stage)
    except Exception as e:  # noqa: BLE001 - reported as an error outcome, never silent
        return done("error", stage, f"{type(e).__name__}: {e}"[:1000])
    finally:
        if workdir is not None and not os.environ.get("REBASE_KEEP_WORKDIR"):
            cleanup(workdir)
