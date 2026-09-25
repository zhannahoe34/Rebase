"""Shared pydantic types (PLAN.md §0.4). Later phases add ResolverResult, VerifierResult, etc."""

from typing import Literal

from pydantic import BaseModel

Category = Literal["lockfile", "migration", "ci", "config", "auth"]
CATEGORIES: tuple[Category, ...] = ("lockfile", "migration", "ci", "config", "auth")


class TouchInfo(BaseModel):
    merged: list[str] = []  # paths in the merged change in this category
    pr: list[str] = []  # paths in the PR in this category


class Signals(BaseModel):
    conflict_count: int  # conflicted files from merge-tree dry run
    conflicted_files: list[str]
    file_overlap: list[str]  # paths changed by both sides
    symbol_overlap: list[str]  # "path:qualname" defs modified by both sides
    diff_lines_merged: int
    diff_lines_pr: int
    touches: dict[Category, TouchInfo]


class PRSummary(BaseModel):  # used for both the merged change and the PR
    intent: str
    touched_areas: list[str]
    behavior_changes: list[str]
    risk_notes: list[str]


class Decision(BaseModel):  # orchestrator output (BAML)
    action: Literal["auto_rebase", "escalate"]
    confidence: float  # 0..1
    reasons: list[str]


class PolicyResult(BaseModel):
    force_escalate: bool
    rules_hit: list[str]  # e.g. "migration:pr+merged:migrations/0003_add_coupons.sql"
    notes: list[str] = []  # reported but not forced (e.g. config files, Q11)


class FinalDecision(BaseModel):
    action: Literal["auto_rebase", "escalate"]
    orchestrator: Decision
    policy: PolicyResult
    # Which checks turned the result into "escalate": policy / orchestrator / confidence_floor.
    escalated_by: list[str] = []
    confidence_floor: float


class Usage(BaseModel):
    """Token usage for one model call, as reported by the API."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0  # 5-minute cache writes
    cache_write_1h_tokens: int = 0  # 1-hour cache writes


class LedgerRow(BaseModel):
    """One row per model call in runs/<run_id>/ledger.jsonl (PLAN.md §0.6)."""

    run_id: str
    pr: str | None
    scenario: str | None
    stage: str  # analyst_merged / analyst_pr / orchestrator / resolver / verifier_intent
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cache_write_1h_tokens: int = 0
    usd_per_mtok: dict[str, float]  # input / output / cache_read / cache_write / cache_write_1h
    cost_usd: float
    cost_source: Literal["estimated", "sdk_reported"]
    recomputed_cost_usd: float | None = None  # sdk_reported rows: tokens x config.PRICES
    latency_s: float
    timestamp: str


class ResolverResult(BaseModel):
    status: Literal["clean", "resolved", "escalated", "error"]
    reason: str | None  # required when escalated/error
    turns: int
    cost_usd: float
    files_touched: list[str]
    head_sha: str | None
    tool_calls: list[str] = []  # tool names in call order (shows skill/MCP use)
    conflict_hunks: dict[str, list[str]] = {}  # every conflict the resolver saw (diff3 style)


class VerifierResult(BaseModel):
    tests_passed: bool
    test_output_tail: str
    intent_preserved: bool
    intent_reasons: list[str]
    verdict: Literal["pass", "escalate"]


class StaleCheckResult(BaseModel):
    unchanged: bool
    within_conflicts: bool = False  # Q4 option 2: changed, but only inside resolved conflicts
    range_diff: str
    reasons: list[str] = []  # why the patch counts as changed (empty when unchanged)


class CostBreakdown(BaseModel):
    per_stage_usd: dict[str, float]
    total_usd: float


class RunOutcome(BaseModel):  # rendered to the PR comment
    pr_number: int | None
    pr_branch: str
    final: Literal["pushed", "escalated", "error"]
    stage: str  # where it ended: policy/orchestrator/resolver/verifier/stale/push
    dry_run: bool  # final == "pushed" without --push means "would push"
    error: str | None = None
    signals: Signals | None
    merged_summary: PRSummary | None
    pr_summary: PRSummary | None
    decision: FinalDecision | None
    resolver: ResolverResult | None = None
    verifier: VerifierResult | None = None
    stale: StaleCheckResult | None = None
    cost: CostBreakdown
    latency_s: float
