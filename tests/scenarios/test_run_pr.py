"""Phase 3 acceptance: full local pipeline, real LLM + real Agent SDK, never mocked.

Without REBASE_ANTHROPIC_API_KEY these are SKIPPED (not run), never passed. Each
outcome's JSON and rendered comment go to runs/pytest-<stamp>/ next to the ledger.
"""

import os
from pathlib import Path

import pytest

from rebase_agent import pipeline
from rebase_agent.ledger import Ledger
from rebase_agent.pipeline import run_pr, summarize_merged
from rebase_agent.report import render
from sandbox_gen.scenarios import SCENARIOS

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not os.environ.get("REBASE_ANTHROPIC_API_KEY"),
        reason="REBASE_ANTHROPIC_API_KEY not set: LLM scenario tests NOT RUN",
    ),
]


def run(name, scenario_repos, llm_run_dir, capsys, *, tag="", force_resolve=False):
    refs = scenario_repos[name]
    ledger = Ledger(llm_run_dir, scenario=name)
    repo = Path(refs.repo)
    merged = summarize_merged(repo, refs.base, refs.main, ledger=ledger)
    outcome = run_pr(
        repo, refs.base, refs.main, refs.pr_branch, merged,
        ledger=ledger, force_resolve=force_resolve,
    )  # fmt: skip
    stem = llm_run_dir / f"outcome-{name}{tag}"
    stem.with_suffix(".json").write_text(outcome.model_dump_json(indent=2))
    stem.with_suffix(".md").write_text(render(outcome))
    with capsys.disabled():
        r = outcome.resolver
        print(
            f"\n[{name}{tag}] final={outcome.final} stage={outcome.stage} "
            f"cost=${outcome.cost.total_usd:.4f} latency={outcome.latency_s}s"
            + (f" resolver={r.status}/{r.turns} turns/{r.reason}" if r else "")
            + (f" error={outcome.error}" if outcome.error else "")
        )
    return outcome


def test_trivial_would_push(scenario_repos, llm_run_dir, capsys):
    o = run("trivial", scenario_repos, llm_run_dir, capsys)
    assert o.resolver.status == "clean"
    assert o.verifier.verdict == "pass"
    assert o.stale.unchanged
    assert (o.final, o.stage, o.dry_run) == ("pushed", "push", True)


def test_real_conflict_resolved_and_would_push(scenario_repos, llm_run_dir, capsys):
    o = run("real_conflict", scenario_repos, llm_run_dir, capsys)
    assert o.resolver.status == "resolved", o.resolver.reason
    assert "mcp__rebase-tools__conflict_preview" in o.resolver.tool_calls
    assert "Skill" in o.resolver.tool_calls
    assert o.verifier.tests_passed and o.verifier.verdict == "pass"
    assert o.stale.unchanged, o.stale.reasons
    assert o.final == "pushed"


def test_semantic_break_force_resolve_caught_by_verifier(scenario_repos, llm_run_dir, capsys):
    o = run("semantic_break", scenario_repos, llm_run_dir, capsys, tag="-force", force_resolve=True)
    assert o.resolver.status == "clean"
    assert not o.verifier.tests_passed
    assert o.verifier.verdict == "escalate"
    assert (o.stage, o.final) == ("verifier", "escalated")


def test_semantic_break_normal_path_note(scenario_repos, llm_run_dir, capsys):
    """Q3: a note, not pass/fail. Only 'never pushed' is asserted."""
    o = run("semantic_break", scenario_repos, llm_run_dir, capsys)
    with capsys.disabled():
        d = o.decision.orchestrator
        print(f"[semantic_break] NOTE orchestrator={d.action} ({d.confidence}): {d.reasons}")
    assert o.final != "pushed"


def assert_never_pushed_at_expected_stage(name, o):
    """For LLM-dependent escalations: `final` is exact, the stage may be any listed one."""
    want = SCENARIOS[name].expected
    assert o.final == want.final == "escalated", o.error
    assert o.stage in (want.stage, *want.also_stages), (o.stage, o.error)


def test_conflicting_intent_is_never_pushed(scenario_repos, llm_run_dir, capsys):
    """A conflict no resolver can settle: escalate at the orchestrator, or (if it tries) at
    the resolver or verifier. Pushing anything would be the failure."""
    o = run("conflicting_intent", scenario_repos, llm_run_dir, capsys)
    assert o.final == "escalated"
    assert_never_pushed_at_expected_stage("conflicting_intent", o)


def test_behavior_change_force_resolve_caught_by_verifier(scenario_repos, llm_run_dir, capsys):
    o = run(
        "behavior_change", scenario_repos, llm_run_dir, capsys, tag="-force", force_resolve=True
    )
    assert o.resolver.status == "clean"
    assert not o.verifier.tests_passed
    assert "pct must be between 0 and 1" in o.verifier.test_output_tail
    assert (o.stage, o.final) == ("verifier", "escalated")


def test_behavior_change_normal_path_is_never_pushed(scenario_repos, llm_run_dir, capsys):
    o = run("behavior_change", scenario_repos, llm_run_dir, capsys)
    with capsys.disabled():
        d = o.decision.orchestrator
        print(f"[behavior_change] NOTE orchestrator={d.action} ({d.confidence}): {d.reasons}")
    assert o.final == "escalated"
    assert_never_pushed_at_expected_stage("behavior_change", o)


def test_multi_file_conflict_resolved_and_would_push(scenario_repos, llm_run_dir, capsys):
    o = run("multi_file_conflict", scenario_repos, llm_run_dir, capsys)
    assert o.resolver.status == "resolved", o.resolver.reason
    assert set(o.resolver.files_touched) == {"shop/shipping.py", "shop/tax.py"}
    assert o.verifier.tests_passed and o.verifier.verdict == "pass"
    assert o.stale.unchanged, o.stale.reasons
    assert (o.final, o.dry_run) == ("pushed", True)


@pytest.mark.parametrize(
    "name", ["migration_collision", "lockfile_touch", "auth_touch", "ci_touch"]
)
def test_policy_scenarios_never_reach_resolver(
    name, scenario_repos, llm_run_dir, capsys, monkeypatch
):
    def forbidden(*a, **k):
        raise AssertionError("resolver must not be constructed for a policy escalation")

    monkeypatch.setattr(pipeline, "prepare_workdir", forbidden)
    monkeypatch.setattr(pipeline, "resolve", forbidden)
    o = run(name, scenario_repos, llm_run_dir, capsys)
    assert (o.stage, o.final) == ("policy", "escalated"), o.error
    assert o.resolver is None


def test_turn_cap_escalates_with_reason(scenario_repos, llm_run_dir, capsys, monkeypatch):
    monkeypatch.setenv("REBASE_RESOLVER_MAX_TURNS", "1")
    o = run("real_conflict", scenario_repos, llm_run_dir, capsys, tag="-cap")
    assert o.resolver.status == "escalated"
    assert "max_turns 1" in o.resolver.reason
    assert (o.stage, o.final) == ("resolver", "escalated")
