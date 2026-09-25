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


def test_wave1_new_scenarios(waves):
    repo, before, after = Path(waves.repo), waves.base, waves.waves[0]
    s = {n: compute_signals(repo, before, after, waves.prs[n]) for n in SCENARIOS}
    p = {n: apply_policy(sig) for n, sig in s.items()}

    assert s["conflicting_intent"].conflict_count == 1
    assert s["conflicting_intent"].symbol_overlap == ["shop/inventory.py:reserve"]
    assert not p["conflicting_intent"].force_escalate  # only judgment can stop it

    assert s["behavior_change"].conflict_count == 0 and s["behavior_change"].symbol_overlap == []
    assert not p["behavior_change"].force_escalate
    assert not rebased_tests_pass(waves, "behavior_change", after)  # verifier must catch it

    assert s["multi_file_conflict"].conflict_count == 2
    assert not p["multi_file_conflict"].force_escalate

    assert p["auth_touch"].force_escalate
    assert [r.split(":")[:2] for r in p["auth_touch"].rules_hit] == [["auth", "pr"]]
    assert p["ci_touch"].force_escalate
    assert [r.split(":")[:2] for r in p["ci_touch"].rules_hit] == [["ci", "pr"]]
    assert rebased_tests_pass(waves, "auth_touch", after)  # would be safe: policy is the stop
    assert rebased_tests_pass(waves, "ci_touch", after)

    assert s["unapproved"].conflict_count == 0 and not p["unapproved"].force_escalate
    assert rebased_tests_pass(waves, "unapproved", after)


def test_prs_of_other_scenarios_are_unaffected_by_each_others_merged_changes(waves):
    """Wave 1 merges every code scenario at once; each PR must see only its own conflicts."""
    repo, before, after = Path(waves.repo), waves.base, waves.waves[0]
    conflicts = {
        n: compute_signals(repo, before, after, waves.prs[n]).conflict_count for n in SCENARIOS
    }
    assert {n: c for n, c in conflicts.items() if c} == {
        "real_conflict": 1,
        "conflicting_intent": 1,
        "multi_file_conflict": 2,
    }


def _wave_of(name: str) -> int:
    return next(i for i, (_, names) in enumerate(WAVES) if name in names)


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_declared_outcome_agrees_with_computed_policy(name, waves):
    """The Expected each scenario declares (and the PR body advertises) must match what the
    deterministic half of the system computes for the wave its change lands in."""
    s = SCENARIOS[name]
    i = _wave_of(name)
    before = waves.base if i == 0 else waves.waves[i - 1]
    signals = compute_signals(Path(waves.repo), before, waves.waves[i], waves.prs[name])
    policy = apply_policy(signals)

    if s.expected.stage == "policy":
        assert policy.force_escalate, name
        assert s.expected.final == "escalated"
    else:
        assert not policy.force_escalate, name
    assert (s.expected.final == "skipped") == (not s.approved), name
    if s.expected.final == "skipped":
        assert s.expected.stage == "eligibility"
    if s.expected.final == "pushed":
        assert s.expected.stage == "push"
    if s.expected.also_stages:  # only LLM-dependent escalations have alternatives
        assert s.expected.final == "escalated" and s.expected.stage != "policy"


def test_every_scenario_pins_its_own_signals_and_a_distinct_purpose():
    assert len({s.description for s in SCENARIOS.values()}) == len(SCENARIOS)
    for name, s in SCENARIOS.items():
        assert set(s.expected_signals) >= {
            "conflict_count", "conflicted_files", "file_overlap", "symbol_overlap", "touches",
        }, name  # fmt: skip
