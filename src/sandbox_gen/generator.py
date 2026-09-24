"""`rebase-sandbox`: build seeded scenario repos.

Local mode builds one git repo per scenario:
  tag `base`    template state (main before the push)
  `pr/<name>`   one commit on top of base (the open PR)
  `main`        one commit on top of base (the merged change)

Idempotent: fixed identities, dates and git config give identical SHAs on every run, and a
rerun deletes and rebuilds the repo (only if this tool created it).
"""

import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import typer

from sandbox_gen.scenarios import SCENARIOS
from sandbox_gen.scenarios.base import Scenario, apply

TEMPLATE = Path(__file__).resolve().parent / "template"
MARKER = "rebase-sandbox-generated"
_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".venv"}
_DATES = {
    "base": "2026-01-01T00:00:00+00:00",
    "pr": "2026-01-02T00:00:00+00:00",
    "merged": "2026-01-03T00:00:00+00:00",
}

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.callback()
def main() -> None:
    """Build seeded scenario repos for the rebase system."""


@dataclass(frozen=True)
class Refs:
    scenario: str
    repo: str
    base: str
    main: str
    pr_branch: str
    pr_head: str


def read_template() -> dict[str, str]:
    tree: dict[str, str] = {}
    for path in sorted(TEMPLATE.rglob("*")):
        rel = path.relative_to(TEMPLATE)
        if path.is_file() and not _SKIP_DIRS.intersection(rel.parts):
            tree[rel.as_posix()] = path.read_text()
    return tree


def _git(repo: Path, *args: str, date: str | None = None) -> str:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Sandbox Bot",
        "GIT_AUTHOR_EMAIL": "sandbox@example.com",
        "GIT_COMMITTER_NAME": "Sandbox Bot",
        "GIT_COMMITTER_EMAIL": "sandbox@example.com",
    }
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=env, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _commit(repo: Path, tree: dict[str, str], message: str, date: str) -> str:
    """Make the worktree match tree exactly, then commit."""
    tracked = _git(repo, "ls-files").splitlines()
    for path in tracked:
        if path not in tree:
            (repo / path).unlink()
    for path, content in tree.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message, date=date)
    return _git(repo, "rev-parse", "HEAD")


def _reset_dir(dest: Path) -> None:
    if dest.exists():
        if not (dest / ".git" / MARKER).exists():
            raise typer.BadParameter(f"{dest} exists and wasn't created by rebase-sandbox")
        shutil.rmtree(dest)
    dest.mkdir(parents=True)


def build_local(dest: Path, scenario: Scenario) -> Refs:
    _reset_dir(dest)
    _git(dest, "init", "-q", "-b", "main")
    (dest / ".git" / MARKER).write_text(scenario.name + "\n")

    base_tree = read_template()
    base = _commit(dest, base_tree, "Initial sandbox state", _DATES["base"])
    _git(dest, "tag", "base")

    pr_branch = f"pr/{scenario.name}"
    _git(dest, "checkout", "-q", "-b", pr_branch)
    pr = scenario.pr
    pr_head = _commit(dest, apply(base_tree, pr.ops), f"{pr.title}\n\n{pr.body}\n", _DATES["pr"])

    _git(dest, "checkout", "-q", "main")
    merged = scenario.merged
    main = _commit(
        dest, apply(base_tree, merged.ops), f"{merged.title}\n\n{merged.body}\n", _DATES["merged"]
    )
    return Refs(scenario.name, str(dest), base, main, pr_branch, pr_head)


@app.command()
def generate(
    local: Annotated[
        Path | None, typer.Option(help="Directory to build scenario repos in (one per scenario).")
    ] = None,
    scenario: Annotated[str, typer.Option(help="Scenario name, or 'all'.")] = "all",
    push: Annotated[bool, typer.Option(help="Reset the GitHub sandbox repo (Phase 4).")] = False,
) -> None:
    """Build scenario repos and print their refs as JSON."""
    if push:
        typer.echo("--push is not implemented yet (planned for Phase 4).", err=True)
        raise typer.Exit(2)
    if local is None:
        raise typer.BadParameter("pass --local DIR")
    if scenario != "all" and scenario not in SCENARIOS:
        raise typer.BadParameter(f"unknown scenario {scenario!r}; choose from {list(SCENARIOS)}")
    names = list(SCENARIOS) if scenario == "all" else [scenario]
    refs = [build_local(local.resolve() / name, SCENARIOS[name]) for name in names]
    typer.echo(json.dumps([asdict(r) for r in refs], indent=2))


if __name__ == "__main__":
    app()
