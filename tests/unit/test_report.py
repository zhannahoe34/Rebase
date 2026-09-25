"""Report rendering snapshot. Regenerate with UPDATE_SNAPSHOTS=1 and review the diff."""

import os
from pathlib import Path

from rebase_agent.models import (
    CATEGORIES,
    CostBreakdown,
    Decision,
    FinalDecision,
    PolicyResult,
    PRSummary,
    ResolverResult,
    RunOutcome,
    Signals,
    StaleCheckResult,
    TouchInfo,
    VerifierResult,
)
from rebase_agent.report import render

SNAPSHOT = Path(__file__).parent / "fixtures" / "report_resolved.md"


def outcome() -> RunOutcome:
    summary = PRSummary(intent="x", touched_areas=[], behavior_changes=[], risk_notes=[])
    return RunOutcome(
        pr_number=7,
        pr_branch="pr/real_conflict",
        final="pushed",
        stage="push",
        dry_run=True,
        signals=Signals(
            conflict_count=1,
            conflicted_files=["shop/inventory.py"],
            file_overlap=["shop/inventory.py"],
            symbol_overlap=["shop/inventory.py:restock"],
            diff_lines_merged=9,
            diff_lines_pr=10,
            touches={c: TouchInfo() for c in CATEGORIES},
        ),
        merged_summary=summary,
        pr_summary=summary,
        decision=FinalDecision(
            action="auto_rebase",
            orchestrator=Decision(
                action="auto_rebase", confidence=0.85, reasons=["Orthogonal checks."]
            ),
            policy=PolicyResult(
                force_escalate=False, rules_hit=[], notes=["config:merged:pyproject.toml"]
            ),
            escalated_by=[],
            confidence_floor=0.7,
        ),
        resolver=ResolverResult(
            status="resolved",
            reason=None,
            turns=11,
            cost_usd=0.0375,
            files_touched=["shop/inventory.py"],
            head_sha="02630f9",
            tool_calls=["Skill", "mcp__rebase-tools__conflict_preview", "mcp__rebase__git_add"],
        ),
        verifier=VerifierResult(
            tests_passed=True,
            test_output_tail="10 passed",
            intent_preserved=True,
            intent_reasons=["Empty-name check present."],
            verdict="pass",
        ),
        stale=StaleCheckResult(unchanged=True, range_diff="1:  0675f8d ! 1:  82df53f Reject\n"),
        cost=CostBreakdown(
            per_stage_usd={"orchestrator": 0.006, "resolver": 0.0375}, total_usd=0.0435
        ),
        latency_s=52.4,
    )


def test_report_snapshot():
    text = render(outcome())
    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT.write_text(text, encoding="utf-8")
    assert text == SNAPSHOT.read_text(encoding="utf-8")


def test_every_final_renders():
    for final, stage in (("escalated", "policy"), ("error", "resolver")):
        o = outcome().model_copy(update={"final": final, "stage": stage, "error": "boom"})
        assert f"`{stage}`" in render(o)
