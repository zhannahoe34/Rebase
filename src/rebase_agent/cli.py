"""`rebase-agent` CLI: signals, setup, decide, run-pr, costs."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from rebase_agent import ledger as ledger_mod
from rebase_agent.ledger import Ledger
from rebase_agent.models import PRSummary
from rebase_agent.pipeline import decide_pr, run_pr, summarize_merged
from rebase_agent.report import render
from rebase_agent.signals import compute_signals

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main() -> None:
    """Agentic auto-rebase for approved PRs."""


@app.command()
def signals(
    repo: Annotated[Path, typer.Option(help="Local clone.")],
    pr_branch: Annotated[str, typer.Option(help="PR head ref.")],
    base: Annotated[str, typer.Option(help="Main before the push (the merged change's parent).")],
    merged: Annotated[str, typer.Option(help="Main after the push.")] = "main",
) -> None:
    """Print deterministic signals for rebasing PR_BRANCH onto MERGED, as JSON."""
    result = compute_signals(repo, base, merged, pr_branch)
    typer.echo(result.model_dump_json(indent=2))


def _run_dir(run_dir: Path | None) -> Path:
    return run_dir or Path("runs") / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


RunDirOpt = Annotated[
    Path | None, typer.Option(help="Where ledger.jsonl goes. Default: runs/<UTC timestamp>.")
]
ScenarioOpt = Annotated[str | None, typer.Option(help="Scenario name for the ledger.")]


@app.command()
def setup(
    repo: Annotated[Path, typer.Option(help="Local clone.")],
    base: Annotated[str, typer.Option(help="Main before the push.")],
    out: Annotated[Path, typer.Option(help="Where to write the merged-change summary JSON.")],
    merged: Annotated[str, typer.Option(help="Main after the push.")] = "main",
    run_dir: RunDirOpt = None,
    scenario: ScenarioOpt = None,
) -> None:
    """Summarize the merged change once (base..merged) and write it to OUT for reuse."""
    ledger = Ledger(_run_dir(run_dir), scenario=scenario)
    summary = summarize_merged(repo, base, merged, ledger=ledger)
    out.write_text(summary.model_dump_json(indent=2) + "\n")
    typer.echo(f"wrote {out}; ledger {ledger.path}", err=True)


@app.command()
def decide(
    repo: Annotated[Path, typer.Option(help="Local clone.")],
    pr_branch: Annotated[str, typer.Option(help="PR head ref.")],
    base: Annotated[str, typer.Option(help="Main before the push.")],
    merged: Annotated[str, typer.Option(help="Main after the push.")] = "main",
    merged_summary: Annotated[
        Path | None, typer.Option(help="Summary JSON from `setup`; computed here if omitted.")
    ] = None,
    run_dir: RunDirOpt = None,
    scenario: ScenarioOpt = None,
) -> None:
    """Print the FinalDecision JSON for one PR (stdout) and its LLM cost (stderr)."""
    ledger = Ledger(_run_dir(run_dir), scenario=scenario)
    if merged_summary is not None:
        summary = PRSummary.model_validate_json(merged_summary.read_text())
    else:
        summary = summarize_merged(repo, base, merged, ledger=ledger)
    final = decide_pr(repo, base, merged, pr_branch, summary, ledger=ledger)
    typer.echo(final.model_dump_json(indent=2))
    totals = ledger_mod.rollup(ledger_mod.read_rows(ledger.run_dir))
    typer.echo(
        f"cost: ${totals['total_usd']:.4f} ({totals['calls']} calls); {ledger.path}", err=True
    )


@app.command("run-pr")
def run_pr_cmd(
    repo: Annotated[Path, typer.Option(help="Local clone.")],
    pr_branch: Annotated[str, typer.Option(help="PR head ref.")],
    base: Annotated[str, typer.Option(help="Main before the push.")],
    merged: Annotated[str, typer.Option(help="Main after the push.")] = "main",
    merged_summary: Annotated[
        Path | None, typer.Option(help="Summary JSON from `setup`; computed here if omitted.")
    ] = None,
    force_resolve: Annotated[
        bool, typer.Option(help="Skip the orchestrator (policy still applies). Q3.")
    ] = False,
    run_dir: RunDirOpt = None,
    scenario: ScenarioOpt = None,
) -> None:
    """Full local pipeline for one PR (no push). Prints the comment markdown; writes
    outcome JSON and markdown next to the ledger."""
    ledger = Ledger(_run_dir(run_dir), scenario=scenario)
    if merged_summary is not None:
        summary = PRSummary.model_validate_json(merged_summary.read_text())
    else:
        summary = summarize_merged(repo, base, merged, ledger=ledger)
    outcome = run_pr(
        repo, base, merged, pr_branch, summary, ledger=ledger, force_resolve=force_resolve
    )
    stem = ledger.run_dir / f"outcome-{pr_branch.replace('/', '_')}"
    stem.with_suffix(".json").write_text(outcome.model_dump_json(indent=2) + "\n")
    comment = render(outcome)
    stem.with_suffix(".md").write_text(comment)
    typer.echo(comment)
    typer.echo(f"{outcome.final} at {outcome.stage}; {stem}.json", err=True)
    if outcome.final == "error":
        raise typer.Exit(1)


@app.command()
def costs(
    run_dir: Annotated[Path, typer.Argument(help="A runs/<run_id> directory.")],
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    """Spend per stage, PR, model and scenario, and the total, from the run's ledger."""
    rows = ledger_mod.read_rows(run_dir)
    if not rows:
        typer.echo(f"no ledger rows in {run_dir}", err=True)
        raise typer.Exit(1)
    summary = ledger_mod.rollup(rows)
    typer.echo(json.dumps(summary, indent=2) if as_json else ledger_mod.format_rollup(summary))
