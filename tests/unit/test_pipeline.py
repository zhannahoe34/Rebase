"""Pipeline plumbing. The analyst and orchestrator are replaced by counting stubs here:
this checks call counts and wiring only. Real-LLM behavior is in tests/scenarios/."""

from pathlib import Path

from rebase_agent import analysts, orchestrator, pipeline
from rebase_agent.models import Decision, PRSummary, Usage

SUMMARY = PRSummary(intent="x", touched_areas=[], behavior_changes=[], risk_notes=[])
USAGE = Usage(input_tokens=0, output_tokens=0)


def test_merged_summary_computed_once_per_run(scenario_repos, monkeypatch):
    calls: list[str] = []

    def summarize(diff, title, body, *, model, stage, ledger, pr=None):
        calls.append(stage)
        return SUMMARY, USAGE

    def decide(signals, merged, pr, *, model, ledger, pr_ref):
        assert merged is SUMMARY
        return Decision(action="auto_rebase", confidence=0.9, reasons=["stub"]), USAGE

    monkeypatch.setattr(analysts, "summarize_change", summarize)
    monkeypatch.setattr(orchestrator, "decide", decide)
    refs = scenario_repos["trivial"]
    prs = [refs.pr_branch, refs.pr_branch, refs.pr_branch]
    results = pipeline.decide_all(Path(refs.repo), refs.base, refs.main, prs, ledger=None)

    assert calls.count("analyst_merged") == 1
    assert calls.count("analyst_pr") == 3
    assert results[refs.pr_branch].action == "auto_rebase"

    calls.clear()
    pipeline.decide_all(
        Path(refs.repo), refs.base, refs.main, prs, ledger=None, merged_summary=SUMMARY
    )
    assert calls.count("analyst_merged") == 0
