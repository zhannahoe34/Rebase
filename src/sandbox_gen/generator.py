"""`rebase-sandbox`: build seeded scenario repos.

Local mode builds one git repo per scenario:
  tag `base`    template state (main before the push)
  `pr/<name>`   one commit on top of base (the open PR)
  `main`        one commit on top of base (the merged change)

Push mode resets the GitHub sandbox (PLAN.md Q5: per-scenario base branches). Every
scenario shares the same base commit, so one repo holds them all:
  `main`, `base/<name>`   the base commit
  `pr/<name>`             the PR, with an open PR `pr/<name>` -> `base/<name>`
`trigger` then fast-forwards `base/<name>` to the merged commit, which is the "merge"
that fires the sandbox's rebase workflow.

Idempotent: fixed identities, dates and git config give identical SHAs on every run, and a
rerun deletes and rebuilds the repo (only if this tool created it).
"""

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

import typer

from rebase_agent.github_api import GitHub, sandbox_repo, token
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
    push: Annotated[
        bool, typer.Option(help="Reset SANDBOX_REPO on GitHub and (re)open the scenario PRs.")
    ] = False,
    remote: Annotated[
        str | None, typer.Option(help="Push URL (default: SANDBOX_REPO with SANDBOX_REPO_TOKEN).")
    ] = None,
    label_approved: Annotated[
        bool, typer.Option(help="With --push: add the rebase:approved label to each new PR.")
    ] = False,
) -> None:
    """Build scenario repos and print their refs as JSON."""
    names = _names(scenario)
    if push:
        _push_scenarios(names, remote, label_approved=label_approved)
        return
    if local is None:
        raise typer.BadParameter("pass --local DIR or --push")
    refs = [build_local(local.resolve() / name, SCENARIOS[name]) for name in names]
    typer.echo(json.dumps([asdict(r) for r in refs], indent=2))


@app.command()
def trigger(
    scenario: Annotated[str, typer.Option(help="Scenario name, or 'all'.")] = "all",
    remote: Annotated[
        str | None, typer.Option(help="Push URL (default: SANDBOX_REPO with SANDBOX_REPO_TOKEN).")
    ] = None,
) -> None:
    """ "Merge": fast-forward base/<name> to the scenario's merged commit on GitHub."""
    with tempfile.TemporaryDirectory() as tmp:
        for name in _names(scenario):
            refs = build_local(Path(tmp) / name, SCENARIOS[name])
            _git(
                Path(refs.repo),
                "push",
                "-q",
                _remote(remote),
                f"{refs.main}:refs/heads/base/{name}",
            )
            typer.echo(f"base/{name} -> {refs.main[:12]} (merged)", err=True)


def _names(scenario: str) -> list[str]:
    if scenario != "all" and scenario not in SCENARIOS:
        raise typer.BadParameter(f"unknown scenario {scenario!r}; choose from {list(SCENARIOS)}")
    return list(SCENARIOS) if scenario == "all" else [scenario]


def _remote(remote: str | None) -> str:
    return remote or f"https://x-access-token:{token()}@github.com/{sandbox_repo()}.git"


PR_MARKER = "<!-- rebase-sandbox scenario -->"


def pr_body(s: Scenario) -> str:
    return (
        f"{s.pr.body}\n\n---\n{PR_MARKER}\nScenario `{s.name}`: {s.description}\n\n"
        f"Expected: **{s.expected.final}** at `{s.expected.stage}`. {s.expected.note}\n"
    )


def _push_scenarios(names: list[str], remote: str | None, *, label_approved: bool) -> None:
    """Force-reset main, base/<name> and pr/<name>, then close any open PR for each
    pr/<name> and open a fresh one. The workflow ignores force-pushes and branch
    creation, so a reset never runs the pipeline."""
    gh = GitHub(sandbox_repo(), token())
    url = _remote(remote)
    with tempfile.TemporaryDirectory() as tmp:
        built = {name: build_local(Path(tmp) / name, SCENARIOS[name]) for name in names}
        first = next(iter(built.values()))
        for name, refs in built.items():
            for pr in gh.open_prs(head=refs.pr_branch):
                gh.close_pr(pr["number"])
                typer.echo(f"closed #{pr['number']} ({refs.pr_branch})", err=True)
        _git(Path(first.repo), "push", "-q", "--force", url, f"{first.base}:refs/heads/main")
        for name, refs in built.items():
            _git(
                Path(refs.repo),
                "push",
                "-q",
                "--force",
                url,
                f"{refs.base}:refs/heads/base/{name}",
                f"{refs.pr_head}:refs/heads/{refs.pr_branch}",
            )
        out = []
        for name, refs in built.items():
            s = SCENARIOS[name]
            pr = gh.create_pr(refs.pr_branch, f"base/{name}", s.pr.title, pr_body(s))
            if label_approved:
                gh.add_label(pr["number"], "rebase:approved")
            typer.echo(f"opened #{pr['number']} {refs.pr_branch} -> base/{name}", err=True)
            out.append({**asdict(refs), "pr_number": pr["number"], "pr_url": pr["html_url"]})
    typer.echo(json.dumps(out, indent=2))


if __name__ == "__main__":
    app()
