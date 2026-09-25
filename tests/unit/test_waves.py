"""Push-mode layout: all PRs target main; merged changes land in waves. Deterministic
checks of what each wave means for each PR (the live acceptance runs on GitHub)."""

import subprocess
import sys
from pathlib import Path

import pytest

from rebase_agent.policy import apply_policy
from rebase_agent.signals import compute_signals
from sandbox_gen.generator import build_waves
from sandbox_gen.scenarios import SCENARIOS, WAVES


@pytest.fixture(scope="module")
def waves(tmp_path_factory):
    return build_waves(tmp_path_factory.mktemp("w") / "waves")


def test_every_scenario_is_in_exactly_one_wave():
    names = [n for _, ns in WAVES for n in ns]
    assert sorted(names) == sorted(SCENARIOS)


def test_waves_are_deterministic(tmp_path, waves):
    again = build_waves(tmp_path / "again")
    assert (again.base, again.waves, again.prs) == (waves.base, waves.waves, waves.prs)


def rebased_tests_pass(waves, name: str, onto: str) -> bool:
    repo = Path(waves.repo)
    wt = repo.parent / f"wt-{name}-{onto[:7]}"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(wt), waves.prs[name]],
        check=True,
    )
    env = {"GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}
    rebase = subprocess.run(
        ["git", "-C", str(wt), "rebase", "-q", onto], capture_output=True, env=env, check=False
    )
    assert rebase.returncode == 0, rebase.stderr
    tests = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=wt,
        capture_output=True,
        check=False,
    )
    return tests.returncode == 0


def test_wave1_code_changes(waves):
    repo, before, after = Path(waves.repo), waves.base, waves.waves[0]
    s = {n: compute_signals(repo, before, after, waves.prs[n]) for n in SCENARIOS}
    p = {n: apply_policy(sig) for n, sig in s.items()}

    assert s["trivial"].conflict_count == 0 and not p["trivial"].force_escalate
    assert rebased_tests_pass(waves, "trivial", after)

    assert s["real_conflict"].conflict_count >= 1
    assert "shop/inventory.py:restock" in s["real_conflict"].symbol_overlap
    assert not p["real_conflict"].force_escalate

    assert s["semantic_break"].conflict_count == 0 and s["semantic_break"].symbol_overlap == []
    assert not rebased_tests_pass(waves, "semantic_break", after)  # verifier must catch it

    assert p["migration_collision"].force_escalate
    assert any(r.startswith("migration:pr:") for r in p["migration_collision"].rules_hit)

    assert s["lockfile_touch"].conflict_count == 0 and not p["lockfile_touch"].force_escalate
    assert rebased_tests_pass(waves, "lockfile_touch", after)


def test_wave2_risky_changes_escalate_every_pr_by_policy(waves):
    repo, before, after = Path(waves.repo), waves.waves[0], waves.waves[1]
    for name in SCENARIOS:
        rules = apply_policy(compute_signals(repo, before, after, waves.prs[name])).rules_hit
        assert any(r.startswith("migration:") for r in rules), name
        assert any(r.startswith("lockfile:merged:") for r in rules), name


def test_migration_numbers_collide_in_wave2(waves):
    repo = Path(waves.repo)
    sig = compute_signals(repo, waves.waves[0], waves.waves[1], waves.prs["migration_collision"])
    touch = sig.touches["migration"]
    assert touch.merged == ["migrations/0003_add_coupons.sql"]
    assert touch.pr == ["migrations/0003_add_wishlist.sql"]
