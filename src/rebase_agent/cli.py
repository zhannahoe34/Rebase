"""`rebase-agent` CLI. Phase 1: `signals`."""

from pathlib import Path
from typing import Annotated

import typer

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
