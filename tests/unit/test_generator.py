import shutil
import subprocess
from pathlib import Path

import pytest
import typer

from sandbox_gen.generator import build_local
from sandbox_gen.scenarios import SCENARIOS

from .conftest import git, run_sandbox_tests


def test_rebuild_is_idempotent(tmp_path, scenario_repos):
    for name, first in scenario_repos.items():
        again = build_local(tmp_path / name, SCENARIOS[name])
        rerun = build_local(tmp_path / name, SCENARIOS[name])  # overwrite in place
        for refs in (again, rerun):
            assert (refs.base, refs.main, refs.pr_head) == (first.base, first.main, first.pr_head)


def test_refuses_to_delete_foreign_directory(tmp_path):
    (tmp_path / "mine").mkdir()
    (tmp_path / "mine" / "keep.txt").write_text("x")
    with pytest.raises(typer.BadParameter):
        build_local(tmp_path / "mine", SCENARIOS["trivial"])
    assert (tmp_path / "mine" / "keep.txt").exists()


def _clone(refs, dest: Path) -> Path:
    shutil.copytree(refs.repo, dest)
    return dest


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_each_side_is_green_on_its_own(name, scenario_repos, tmp_path):
    repo = _clone(scenario_repos[name], tmp_path / "r")
    for ref in ("base", "main", f"pr/{name}"):
        git(repo, "checkout", "-q", ref)
        result = run_sandbox_tests(repo)
        assert result.returncode == 0, f"{ref}:\n{result.stdout}"


@pytest.mark.parametrize(
    "name, tests_pass",
    [
        ("trivial", True),
        ("migration_collision", True),
        ("lockfile_touch", True),
        ("semantic_break", False),
        ("behavior_change", False),
        ("auth_touch", True),
        ("ci_touch", True),
        ("unapproved", True),
    ],
)
def test_clean_rebase_outcomes(name, tests_pass, scenario_repos, tmp_path):
    repo = _clone(scenario_repos[name], tmp_path / "r")
    git(repo, "checkout", "-q", f"pr/{name}")
    assert git(repo, "rebase", "main", check=False).returncode == 0
    result = run_sandbox_tests(repo)
    assert (result.returncode == 0) is tests_pass, result.stdout
    if name == "semantic_break":
        assert "TypeError" in result.stdout and "tax_rate" in result.stdout
    if name == "behavior_change":  # no signature change: the failure is a wrong value
        assert "pct must be between 0 and 1" in result.stdout


def _keep_both_sides(text: str) -> str:
    out, in_conflict = [], False
    for line in text.splitlines(keepends=True):
        if line.startswith(("<<<<<<< ", "=======", ">>>>>>> ")):
            in_conflict = not line.startswith(">>>>>>> ")
            continue
        out.append(line)
    assert not in_conflict
    return "".join(out)


@pytest.mark.parametrize(
    "name, files",
    [
        ("real_conflict", ["shop/inventory.py"]),
        ("multi_file_conflict", ["shop/shipping.py", "shop/tax.py"]),
    ],
)
def test_conflicts_are_resolvable_by_keeping_both(name, files, scenario_repos, tmp_path):
    repo = _clone(scenario_repos[name], tmp_path / "r")
    git(repo, "checkout", "-q", f"pr/{name}")
    assert git(repo, "rebase", "main", check=False).returncode != 0
    conflicted = git(repo, "diff", "--name-only", "--diff-filter=U").stdout.split()
    assert conflicted == files

    for file in files:
        path = repo / file
        path.write_text(_keep_both_sides(path.read_text()))
        git(repo, "add", file)
    git(repo, "-c", "core.editor=true", "rebase", "--continue")

    result = run_sandbox_tests(repo)
    assert result.returncode == 0, result.stdout

    # The PR's own added lines survive unchanged (what the stale check will compare; Q4).
    def added(rev: str, file: str) -> list[str]:
        diff = git(repo, "show", "--format=", rev, "--", file).stdout
        return [ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]

    for file in files:
        original = added(scenario_repos[name].pr_head, file)
        assert original
        assert added("HEAD", file) == original


@pytest.mark.parametrize("strategy", ["keep_both", "ours", "theirs"])
def test_conflicting_intent_has_no_mechanical_resolution(strategy, scenario_repos, tmp_path):
    """Whichever side wins (or both are kept), some test of the other side fails: nothing a
    resolver does mechanically can be right, so a human has to decide."""
    repo = _clone(scenario_repos["conflicting_intent"], tmp_path / "r")
    git(repo, "checkout", "-q", "pr/conflicting_intent")
    assert git(repo, "rebase", "main", check=False).returncode != 0
    assert git(repo, "diff", "--name-only", "--diff-filter=U").stdout.split() == [
        "shop/inventory.py"
    ]

    path = repo / "shop/inventory.py"
    if strategy == "keep_both":
        path.write_text(_keep_both_sides(path.read_text()))
    else:  # during a rebase, "ours" is the branch being rebased onto (main)
        git(repo, "checkout", f"--{strategy}", "shop/inventory.py")
    git(repo, "add", "shop/inventory.py")
    git(repo, "-c", "core.editor=true", "rebase", "--continue")

    result = run_sandbox_tests(repo)
    assert result.returncode != 0, f"{strategy} unexpectedly passes:\n{result.stdout}"


def test_all_scenarios_share_one_base_commit(scenario_repos):
    """Push mode relies on this: main and every base/<name> start at the same commit."""
    assert len({refs.base for refs in scenario_repos.values()}) == 1


def test_rebase_workflow_skips_resets_and_never_pushes_base():
    from sandbox_gen.generator import read_template

    wf = read_template()[".github/workflows/rebase.yml"]
    assert "!github.event.forced" in wf  # generator resets are force-pushes
    assert "0000000000000000000000000000000000000000" in wf  # branch creation
    assert "branches: [main]" in wf
    assert "--push" in wf and "SANDBOX_REPO_TOKEN" in wf and "GITHUB_TOKEN" not in wf


def test_push_needs_a_token(monkeypatch):
    from typer.testing import CliRunner

    from sandbox_gen.generator import app

    monkeypatch.delenv("SANDBOX_REPO_TOKEN", raising=False)
    result = CliRunner().invoke(app, ["generate", "--push", "--scenario", "trivial"])
    assert result.exit_code != 0
    assert "SANDBOX_REPO_TOKEN" in str(result.exception)


@pytest.mark.parametrize("src", ["template", "assets/lockfile_touch"])
def test_sandbox_lockfiles_match_pyproject(src, tmp_path):
    """The sandbox CI runs `uv sync --locked`; a lock/pyproject mismatch fails every run."""
    root = Path(__file__).resolve().parents[2] / "src/sandbox_gen" / src
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy(root / name, tmp_path / name)
    proc = subprocess.run(
        ["uv", "lock", "--check"], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr


class FakeGitHub:
    """Stands in for the REST client: records what the generator asks GitHub to do."""

    def __init__(self, *a, **k):
        self.created, self.updated, self.labels, self.closed = [], [], [], []

    def open_prs(self, base=None, head=None):
        return []

    def create_pr(self, head, base, title, body):
        self.created.append((head, base, title, body))
        return {"number": 100 + len(self.created), "html_url": f"https://x/{head}"}

    def update_pr(self, number, **fields):  # pragma: no cover - no PRs pre-exist here
        self.updated.append(number)
        return {"number": number, "html_url": "https://x"}

    def close_pr(self, number):  # pragma: no cover
        self.closed.append(number)

    def add_label(self, number, label):
        self.labels.append(("add", number, label))

    def remove_label(self, number, label):
        self.labels.append(("remove", number, label))


@pytest.fixture
def pushed(tmp_path, monkeypatch):
    """Run `generate --push --label-approved` against a bare local remote and a fake GitHub."""
    from typer.testing import CliRunner

    from sandbox_gen import generator

    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    fake = FakeGitHub()
    monkeypatch.setenv("SANDBOX_REPO_TOKEN", "tok")
    monkeypatch.setattr(generator, "GitHub", lambda *a, **k: fake)
    result = CliRunner().invoke(
        generator.app, ["generate", "--push", "--label-approved", "--remote", str(remote)]
    )
    assert result.exit_code == 0, result.output
    return remote, fake


def test_push_resets_main_to_base_and_pushes_every_pr_branch(pushed):
    remote, _ = pushed
    heads = subprocess.run(
        ["git", "-C", str(remote), "for-each-ref", "--format=%(refname:short)", "refs/heads"],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    assert sorted(heads) == sorted(["main", *(f"pr/{n}" for n in SCENARIOS)])
    log = subprocess.run(
        ["git", "-C", str(remote), "log", "--format=%s", "main"],
        capture_output=True, text=True, check=True,
    ).stdout.split("\n")  # fmt: skip
    assert log[0] == "Initial sandbox state"  # main is the base commit, no wave merged


def test_push_opens_one_pr_per_scenario_against_main(pushed):
    _, fake = pushed
    assert sorted(h for h, *_ in fake.created) == sorted(f"pr/{n}" for n in SCENARIOS)
    assert {base for _, base, *_ in fake.created} == {"main"}
    bodies = {head: body for head, _, _, body in fake.created}
    assert "`orchestrator` or `resolver` or `verifier`" in bodies["pr/conflicting_intent"]
    assert "**skipped** at `eligibility`" in bodies["pr/unapproved"]
    assert "**escalated** at `policy`" in bodies["pr/auth_touch"]


def test_only_approved_scenarios_get_the_approval_label(pushed):
    _, fake = pushed
    numbers = {head: 101 + i for i, (head, *_) in enumerate(fake.created)}
    removed = {n for verb, n, _ in fake.labels if verb == "remove"}
    added = {n for verb, n, _ in fake.labels if verb == "add"}
    assert removed == {numbers[f"pr/{n}"] for n, s in SCENARIOS.items() if not s.approved}
    assert added == {numbers[f"pr/{n}"] for n, s in SCENARIOS.items() if s.approved}
    assert removed == {numbers["pr/unapproved"]}
    assert all(label == "rebase:approved" for _, _, label in fake.labels)
