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


def _keep_both_sides(text: str) -> str:
    out, in_conflict = [], False
    for line in text.splitlines(keepends=True):
        if line.startswith(("<<<<<<< ", "=======", ">>>>>>> ")):
            in_conflict = not line.startswith(">>>>>>> ")
            continue
        out.append(line)
    assert not in_conflict
    return "".join(out)


def test_real_conflict_is_resolvable_by_keeping_both(scenario_repos, tmp_path):
    repo = _clone(scenario_repos["real_conflict"], tmp_path / "r")
    git(repo, "checkout", "-q", "pr/real_conflict")
    assert git(repo, "rebase", "main", check=False).returncode != 0
    conflicted = git(repo, "diff", "--name-only", "--diff-filter=U").stdout.split()
    assert conflicted == ["shop/inventory.py"]

    path = repo / "shop/inventory.py"
    path.write_text(_keep_both_sides(path.read_text()))
    git(repo, "add", "shop/inventory.py")
    git(repo, "-c", "core.editor=true", "rebase", "--continue")

    result = run_sandbox_tests(repo)
    assert result.returncode == 0, result.stdout

    # The PR's own added lines survive unchanged (what the stale check will compare; Q4).
    def added(rev: str) -> list[str]:
        diff = git(repo, "show", "--format=", rev, "--", "shop/inventory.py").stdout
        return [ln for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++")]

    original = added(scenario_repos["real_conflict"].pr_head)
    assert original
    assert added("HEAD") == original


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
