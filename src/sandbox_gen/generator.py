"""`rebase-sandbox`: build seeded scenario repos.

Local mode builds one git repo per scenario:
  tag `base`    template state (main before the push)
  `pr/<name>`   one commit on top of base (the open PR)
  `main`        one commit on top of base (the merged change)

Push mode resets the GitHub sandbox so it looks like a real repo (PLAN.md Q5):
  `main`        the base commit
  `pr/<name>`   one branch per scenario, each with an open PR `pr/<name>` -> `main`
`trigger --wave N` then fast-forwards main by one merge commit that lands a wave of
scenarios' merged changes (`scenarios.WAVES`); that push fires the rebase workflow for
every open eligible PR. Every scenario shares the same base commit, which makes this work.

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
from sandbox_gen.scenarios import SCENARIOS, WAVES
from sandbox_gen.scenarios.base import Scenario, apply

TEMPLATE = Path(__file__).resolve().parent / "template"
MARKER = "rebase-sandbox-generated"
_SKIP_DIRS = {"__pycache__", ".pytest_cache", ".venv"}
_DATES = {
    "base": "2026-01-01T00:00:00+00:00",
    "pr": "2026-01-02T00:00:00+00:00",
    "merged": "2026-01-03T00:00:00+00:00",
}
_WAVE_DATE = "2026-01-{day:02d}T00:00:00+00:00"  # wave N is dated Jan (3 + N)

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


@dataclass(frozen=True)
class WaveRefs:
    repo: str
    base: str
    waves: list[str]  # merge commit per wave, each on top of the previous one
    prs: dict[str, str]  # scenario -> PR head sha (branch pr/<name>)


def wave_message(index: int) -> str:
    label, names = WAVES[index]
    lines = [
        f"Merge wave {index + 1} ({label}): " + "; ".join(SCENARIOS[n].merged.title for n in names),
        "",
    ]
    for n in names:
        m = SCENARIOS[n].merged
        lines += [f"- {m.title}: {m.body}"]
    return "\n".join(lines) + "\n"


def build_waves(dest: Path) -> WaveRefs:
    """One repo: main = base + one commit per wave; pr/<name> for every scenario."""
    _reset_dir(dest)
    _git(dest, "init", "-q", "-b", "main")
    (dest / ".git" / MARKER).write_text("waves\n")
    base_tree = read_template()
    base = _commit(dest, base_tree, "Initial sandbox state", _DATES["base"])
    prs: dict[str, str] = {}
    for name, s in SCENARIOS.items():
        _git(dest, "checkout", "-q", "-b", f"pr/{name}", base)
        prs[name] = _commit(
            dest, apply(base_tree, s.pr.ops), f"{s.pr.title}\n\n{s.pr.body}\n", _DATES["pr"]
        )
    _git(dest, "checkout", "-q", "main")
    tree, waves = base_tree, []
    for i, (_, names) in enumerate(WAVES):
        for n in names:
            tree = apply(tree, SCENARIOS[n].merged.ops)
        waves.append(_commit(dest, tree, wave_message(i), _WAVE_DATE.format(day=4 + i)))
    _git(dest, "reset", "-q", "--hard", base)  # main stays at base; waves are reachable by SHA
    for i, sha in enumerate(waves):
        _git(dest, "tag", f"wave/{i + 1}", sha)
    return WaveRefs(str(dest), base, waves, prs)


@app.command()
def generate(
    local: Annotated[
        Path | None, typer.Option(help="Directory to build scenario repos in (one per scenario).")
    ] = None,
    scenario: Annotated[str, typer.Option(help="Scenario name, or 'all' (local mode).")] = "all",
    push: Annotated[
        bool, typer.Option(help="Reset SANDBOX_REPO on GitHub: main at base, one PR per scenario.")
    ] = False,
    remote: Annotated[
        str | None, typer.Option(help="Push URL (default: SANDBOX_REPO with SANDBOX_REPO_TOKEN).")
    ] = None,
    fresh: Annotated[
        bool, typer.Option(help="With --push: close existing scenario PRs and open new ones.")
    ] = False,
    label_approved: Annotated[
        bool, typer.Option(help="With --push: add the rebase:approved label to each PR.")
    ] = False,
) -> None:
    """Build scenario repos (local) or reset the GitHub sandbox (push)."""
    if push:
        _push_waves(remote, fresh=fresh, label_approved=label_approved)
        return
    names = _names(scenario)
    if local is None:
        raise typer.BadParameter("pass --local DIR or --push")
    refs = [build_local(local.resolve() / name, SCENARIOS[name]) for name in names]
    typer.echo(json.dumps([asdict(r) for r in refs], indent=2))


@app.command()
def trigger(
    wave: Annotated[int, typer.Option(help=f"Wave number, 1..{len(WAVES)}.")],
    remote: Annotated[
        str | None, typer.Option(help="Push URL (default: SANDBOX_REPO with SANDBOX_REPO_TOKEN).")
    ] = None,
) -> None:
    """ "Merge": fast-forward main by wave N's merge commit (main must be at wave N-1)."""
    if not 1 <= wave <= len(WAVES):
        raise typer.BadParameter(f"wave must be 1..{len(WAVES)}")
    url = _remote(remote)
    with tempfile.TemporaryDirectory() as tmp:
        refs = build_waves(Path(tmp) / "waves")
        repo = Path(refs.repo)
        expected = refs.base if wave == 1 else refs.waves[wave - 2]
        current = _git(repo, "ls-remote", url, "refs/heads/main").split("\t")[0]
        if current != expected:
            raise typer.BadParameter(
                f"remote main is at {current[:12]}, expected {expected[:12]} "
                f"(wave {wave - 1 or 'base'}); trigger waves in order, or re-run generate --push"
            )
        _git(repo, "push", "-q", url, f"{refs.waves[wave - 1]}:refs/heads/main")
    label, names = WAVES[wave - 1]
    typer.echo(
        f"main -> wave {wave} ({label}: {', '.join(names)}) {refs.waves[wave - 1][:12]}", err=True
    )


def _names(scenario: str) -> list[str]:
    if scenario != "all" and scenario not in SCENARIOS:
        raise typer.BadParameter(f"unknown scenario {scenario!r}; choose from {list(SCENARIOS)}")
    return list(SCENARIOS) if scenario == "all" else [scenario]


def _remote(remote: str | None) -> str:
    return remote or f"https://x-access-token:{token()}@github.com/{sandbox_repo()}.git"


PR_MARKER = "<!-- rebase-sandbox scenario -->"


def pr_body(s: Scenario) -> str:
    wave = next(i + 1 for i, (_, names) in enumerate(WAVES) if s.name in names)
    return (
        f"{s.pr.body}\n\n---\n{PR_MARKER}\nScenario `{s.name}`: {s.description}\n\n"
        f"Its merged change lands on main in wave {wave}. Expected then: "
        f"**{s.expected.final}** at `{s.expected.stage}`. {s.expected.note}\n"
    )


def _push_waves(remote: str | None, *, fresh: bool, label_approved: bool) -> None:
    """Force-reset main and every pr/<name>, delete leftover base/* branches from the old
    layout, then (re)target one open PR per scenario at main. The workflow ignores
    force-pushes and branch creation, so a reset never runs the pipeline."""
    gh = GitHub(sandbox_repo(), token())
    url = _remote(remote)
    with tempfile.TemporaryDirectory() as tmp:
        refs = build_waves(Path(tmp) / "waves")
        repo = Path(refs.repo)
        if fresh:
            for name in SCENARIOS:
                for pr in gh.open_prs(head=f"pr/{name}"):
                    gh.close_pr(pr["number"])
                    typer.echo(f"closed #{pr['number']}", err=True)
        refspecs = [f"{refs.base}:refs/heads/main"]
        refspecs += [f"{sha}:refs/heads/pr/{name}" for name, sha in refs.prs.items()]
        _git(repo, "push", "-q", "--force", url, *refspecs)
        stale = [
            line.split("\t")[1]
            for line in _git(repo, "ls-remote", url, "refs/heads/base/*").splitlines()
            if "\t" in line
        ]
        if stale:
            try:
                _git(repo, "push", "-q", "--delete", url, *stale)
                typer.echo(f"deleted {len(stale)} old base/* branches", err=True)
            except RuntimeError as e:  # cleanup only; never block the reset on it
                typer.echo(f"warning: could not delete {', '.join(stale)}: {e}", err=True)
        # Look PRs up after pushing: when the template changes, the new commits share no
        # history with an old PR's base and GitHub closes that PR on the force-push.
        existing = {name: gh.open_prs(head=f"pr/{name}") for name in SCENARIOS}
        out = []
        for name, s in SCENARIOS.items():
            fields = {"title": s.pr.title, "body": pr_body(s)}
            if existing[name]:
                pr = gh.update_pr(existing[name][0]["number"], base="main", **fields)
                verb = "retargeted"
            else:
                pr = gh.create_pr(f"pr/{name}", "main", **fields)
                verb = "opened"
            if label_approved:
                gh.add_label(pr["number"], "rebase:approved")
            typer.echo(f"{verb} #{pr['number']} pr/{name} -> main", err=True)
            out.append({"scenario": name, "pr_number": pr["number"], "pr_url": pr["html_url"]})
    typer.echo(json.dumps(out, indent=2))


if __name__ == "__main__":
    app()
