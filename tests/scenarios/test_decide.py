"""Phase 2 acceptance: real LLM, real git, default models. Never mocked.

Without REBASE_ANTHROPIC_API_KEY these are SKIPPED (not run), never passed. Every call
is written to runs/pytest-<stamp>/ledger.jsonl; decisions go to decisions.jsonl there.
"""

import json
import os
from pathlib import Path

import pytest

from rebase_agent.ledger import Ledger
from rebase_agent.pipeline import decide_pr, summarize_merged

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(
        not os.environ.get("REBASE_ANTHROPIC_API_KEY"),
        reason="REBASE_ANTHROPIC_API_KEY not set: LLM scenario tests NOT RUN",
    ),
]


def run(name, scenario_repos, llm_run_dir, capsys):
    refs = scenario_repos[name]
    ledger = Ledger(llm_run_dir, scenario=name)
    repo = Path(refs.repo)
    merged = summarize_merged(repo, refs.base, refs.main, ledger=ledger)
    final = decide_pr(repo, refs.base, refs.main, refs.pr_branch, merged, ledger=ledger)
    with (llm_run_dir / "decisions.jsonl").open("a") as f:
        f.write(json.dumps({"scenario": name, **final.model_dump()}) + "\n")
    with capsys.disabled():
        o = final.orchestrator
        print(f"\n[{name}] final={final.action} escalated_by={final.escalated_by}")
        print(f"[{name}] orchestrator={o.action} confidence={o.confidence}")
        for reason in o.reasons:
            print(f"[{name}]   - {reason}")
        print(f"[{name}] rules_hit={final.policy.rules_hit} notes={final.policy.notes}")
    return final


@pytest.mark.parametrize(
    "name,category",
    [
        ("migration_collision", "migration"),
        ("lockfile_touch", "lockfile"),
        ("auth_touch", "auth"),
        ("ci_touch", "ci"),
    ],
)
def test_policy_scenarios_escalate_with_rule(name, category, scenario_repos, llm_run_dir, capsys):
    final = run(name, scenario_repos, llm_run_dir, capsys)
    assert final.action == "escalate"
    assert "policy" in final.escalated_by
    assert any(rule.startswith(f"{category}:") for rule in final.policy.rules_hit)


@pytest.mark.parametrize("name", ["trivial", "real_conflict", "multi_file_conflict"])
def test_safe_scenarios_auto_rebase(name, scenario_repos, llm_run_dir, capsys):
    final = run(name, scenario_repos, llm_run_dir, capsys)
    assert final.action == "auto_rebase", final.orchestrator.reasons


def test_semantic_break_orchestrator_note(scenario_repos, llm_run_dir, capsys):
    """Q3: recorded as a note, not pass/fail. The pass/fail check is --force-resolve (Phase 3)."""
    final = run("semantic_break", scenario_repos, llm_run_dir, capsys)
    assert final.policy.rules_hit == []  # only the policy half is deterministic here


@pytest.mark.parametrize("name", ["conflicting_intent", "behavior_change"])
def test_hard_semantic_scenarios_orchestrator_note(name, scenario_repos, llm_run_dir, capsys):
    """Recorded as notes, not pass/fail (Q3): the orchestrator may or may not spot them; the
    verifier is the backstop, tested in test_run_pr. Only policy's half is deterministic."""
    final = run(name, scenario_repos, llm_run_dir, capsys)
    assert final.policy.rules_hit == []
