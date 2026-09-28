"""`rebase-agent` CLI: signals, setup, decide, run-pr, costs."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from rebase_agent import ledger as ledger_mod
from rebase_agent.git_ops import git
from rebase_agent.github_api import GitHub, PushTarget, sandbox_repo
from rebase_agent.github_api import token as gh_token
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
    github_base: Annotated[
        str | None,
        typer.Option(help="List open PRs targeting this branch on SANDBOX_REPO (Actions)."),
    ] = None,
    matrix_out: Annotated[
        Path | None, typer.Option(help="With --github-base: write eligible PR numbers as JSON.")
    ] = None,
    run_dir: RunDirOpt = None,
    scenario: ScenarioOpt = None,
) -> None:
    """Summarize the merged change once (base..merged) and write it to OUT for reuse.

    With --github-base, first list eligible PRs (approved review or the approval label);
    the summary is skipped when none are eligible, so a no-op run costs nothing."""
    for path in (out, matrix_out):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
    if github_base is not None:
        gh = GitHub(sandbox_repo(), gh_token())
        eligible: list[int] = []
        for pr in gh.open_prs(base=github_base):
            ok, why = gh.eligibility(pr)
            typer.echo(
                f"#{pr['number']} {pr['head']['ref']}: {'eligible' if ok else 'skip'} ({why})",
                err=True,
            )
            if ok:
                eligible.append(pr["number"])
        if matrix_out is not None:
            matrix_out.write_text(json.dumps(eligible) + "\n")
        if not eligible:
            typer.echo("no eligible PRs; merged summary not computed", err=True)
            return
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
    base: Annotated[str, typer.Option(help="Main before the push.")],
    pr_branch: Annotated[
        str | None, typer.Option(help="PR head ref (local mode; or use --pr).")
    ] = None,
    pr: Annotated[
        int | None, typer.Option(help="PR number on SANDBOX_REPO; fetches its head branch.")
    ] = None,
    merged: Annotated[str, typer.Option(help="Main after the push.")] = "main",
    merged_summary: Annotated[
        Path | None, typer.Option(help="Summary JSON from `setup`; computed here if omitted.")
    ] = None,
    force_resolve: Annotated[
        bool, typer.Option(help="Skip the orchestrator (policy still applies). Q3.")
    ] = False,
    push: Annotated[
        bool, typer.Option(help="With --pr: push the rebased branch (force-with-lease).")
    ] = False,
    comment: Annotated[bool, typer.Option(help="With --pr: post the outcome comment.")] = True,
    run_dir: RunDirOpt = None,
    scenario: ScenarioOpt = None,
) -> None:
    """Full pipeline for one PR. Prints the comment markdown and writes outcome JSON and
    markdown next to the ledger. With --pr it comments on every outcome, errors included."""
    if (pr is None) == (pr_branch is None):
        raise typer.BadParameter("give exactly one of --pr-branch or --pr")
    if push and pr is None:
        raise typer.BadParameter("--push needs --pr")
    gh = GitHub(sandbox_repo(), gh_token()) if pr is not None else None
    target: PushTarget | None = None
    if gh is not None:
        info = gh.get_pr(pr)
        head_ref, head_sha = info["head"]["ref"], info["head"]["sha"]
        git(
            repo,
            "fetch",
            "--quiet",
            "origin",
            f"+refs/heads/{head_ref}:refs/remotes/origin/{head_ref}",
        )
        pr_branch = f"origin/{head_ref}"
        if push:
            target = PushTarget(url=gh.push_url(), branch=head_ref, expected_sha=head_sha)

    ledger = Ledger(_run_dir(run_dir), scenario=scenario)
    if merged_summary is not None:
        summary = PRSummary.model_validate_json(merged_summary.read_text())
    else:
        summary = summarize_merged(repo, base, merged, ledger=ledger)
    outcome = run_pr(
        repo,
        base,
        merged,
        pr_branch,
        summary,
        ledger=ledger,
        pr_number=pr,
        force_resolve=force_resolve,
        push=target,
    )
    stem = ledger.run_dir / f"outcome-{pr_branch.replace('/', '_')}"
    stem.with_suffix(".json").write_text(outcome.model_dump_json(indent=2) + "\n")
    text = render(outcome)
    stem.with_suffix(".md").write_text(text)
    typer.echo(text)
    typer.echo(f"{outcome.final} at {outcome.stage}; {stem}.json", err=True)
    if gh is not None and comment:
        typer.echo(f"commented: {gh.post_comment(pr, text)}", err=True)
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
