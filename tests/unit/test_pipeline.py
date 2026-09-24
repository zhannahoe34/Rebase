"""Pipeline plumbing. The analyst and orchestrator are replaced by counting stubs here:
this checks call counts and wiring only. Real-LLM behavior is in tests/scenarios/."""

from pathlib import Path

from rebase_agent import analysts, orchestrator, pipeline
from rebase_agent.ledger import Ledger, read_rows
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


def test_run_pr_cost_counts_only_this_call(tmp_path):
    from rebase_agent.pipeline import _cost

    ledger = Ledger(tmp_path / "run", scenario="s1")
    u = Usage(input_tokens=1_000_000, output_tokens=0)
    haiku = "claude-haiku-4-5-20251001"
    ledger.record(stage="analyst_merged", model=haiku, usage=u, latency_s=0)  # shared, $1
    Ledger(tmp_path / "run", scenario="s2").record(
        stage="analyst_merged", model=haiku, usage=u, latency_s=0
    )  # other scenario's merged summary: excluded
    ledger.record(stage="analyst_pr", model=haiku, usage=u, latency_s=0, pr="pr/x")  # earlier run
    first = len(read_rows(ledger.run_dir))
    ledger.record(stage="analyst_pr", model=haiku, usage=u, latency_s=0, pr="pr/x")
    ledger.record(stage="analyst_pr", model=haiku, usage=u, latency_s=0, pr="pr/y")
    cost = _cost(ledger, "pr/x", first)
    assert cost.per_stage_usd == {"analyst_merged": 1.0, "analyst_pr": 1.0}
    assert cost.total_usd == 2.0
