"""Resolver tools and budget without an LLM: scoping, guardrails, and the clean path."""

from pathlib import Path

import anyio
import pytest

from rebase_agent.config import Caps
from rebase_agent.models import PRSummary
from rebase_agent.resolver.agent import prepare_workdir, resolve
from rebase_agent.resolver.budget import Budget
from rebase_agent.resolver.tools import ToolError, Workdir

PR = PRSummary(intent="x", touched_areas=[], behavior_changes=[], risk_notes=[])


@pytest.fixture
def conflicted(scenario_repos):
    """A workdir paused on real_conflict's rebase conflict."""
    refs = scenario_repos["real_conflict"]
    workdir, onto, _ = prepare_workdir(Path(refs.repo), refs.main, refs.pr_branch)
    wd = Workdir(workdir)
    assert wd.git("rebase", onto).returncode != 0
    return wd


def test_clone_has_no_remote(conflicted):
    assert conflicted.git("remote").stdout.strip() == ""


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/passwd", ".git/config", "a/../../x"])
def test_path_escape_rejected(conflicted, path):
    with pytest.raises(ToolError):
        conflicted.read_file(path)
    with pytest.raises(ToolError):
        conflicted.write_file(path, "x")


def test_only_conflicted_files_are_writable(conflicted):
    assert conflicted.conflicted() == ["shop/inventory.py"]
    with pytest.raises(ToolError, match="not a conflicted file"):
        conflicted.write_file("shop/pricing.py", "x")


def test_git_add_refuses_remaining_markers(conflicted):
    with pytest.raises(ToolError, match="markers remain"):
        conflicted.git_add("shop/inventory.py")


def test_manual_resolution_through_tools(conflicted):
    """Keep both sides by hand, as the agent should, and finish the rebase."""
    text = conflicted.read_file("shop/inventory.py")
    assert "|||||||" in text  # the clone uses diff3 markers
    lines, out, side = text.splitlines(keepends=True), [], None
    for line in lines:
        if line.startswith("<<<<<<<"):
            side = "ours"
        elif line.startswith("|||||||") and side:
            side = "base"  # diff3: the common ancestor's lines are dropped
        elif line.startswith("=======") and side:
            side = "theirs"
        elif line.startswith(">>>>>>>") and side:
            side = None
        elif side != "base":
            out.append(line)
    conflicted.write_file("shop/inventory.py", "".join(out))
    assert conflicted.run_tests().startswith("PASSED")
    assert conflicted.git_add("shop/inventory.py") == "staged shop/inventory.py"
    assert conflicted.rebase_continue().startswith("rebase complete")
    assert not conflicted.rebase_in_progress()
    assert conflicted.files_touched == {"shop/inventory.py"}


def test_rebase_continue_refuses_with_unresolved_files(conflicted):
    with pytest.raises(ToolError, match="unresolved"):
        conflicted.rebase_continue()


def test_escalate_records_reason(conflicted):
    conflicted.escalate("  intents conflict  ")
    assert conflicted.escalation == "intents conflict"


def test_clean_rebase_never_starts_the_agent(scenario_repos, monkeypatch):
    monkeypatch.delenv("REBASE_ANTHROPIC_API_KEY", raising=False)  # agent would need it
    refs = scenario_repos["trivial"]
    workdir, onto, _ = prepare_workdir(Path(refs.repo), refs.main, refs.pr_branch)
    result = anyio.run(lambda: resolve(workdir, onto, PR, Caps(20, 1.0), model="claude-sonnet-5"))
    assert (result.status, result.turns, result.cost_usd) == ("clean", 0, 0.0)
    assert result.head_sha


def test_budget_reasons():
    b = Budget(Caps(max_turns=2, max_usd=0.5))
    assert b.result_reason("success", 0.1) is None
    assert b.result_reason("error_max_turns", 0.1) == "max_turns 2 reached"
    assert "max_usd 0.50" in b.result_reason("error_max_budget_usd", 0.6)
    assert "exceeded" in b.result_reason("success", 0.6)
    for mid in ("a", "a", "b", "c"):
        b.observe_assistant(mid)
    assert b.turns == 3
    assert b.over_turns() == "max_turns 2 reached"
