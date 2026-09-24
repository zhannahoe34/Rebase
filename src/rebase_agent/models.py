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
    cache_write_tokens: int = 0


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
    usd_per_mtok: dict[str, float]  # input / output / cache_read / cache_write
    cost_usd: float
    cost_source: Literal["estimated", "sdk_reported"]
    latency_s: float
    timestamp: str
