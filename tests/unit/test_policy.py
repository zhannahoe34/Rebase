"""Policy guardrails (D6). Hand-built Decisions test the combine logic, not the LLM."""

import itertools

import pytest

from rebase_agent import config
from rebase_agent.models import CATEGORIES, Decision, PolicyResult, Signals, TouchInfo
from rebase_agent.policy import apply_policy, combine


def signals(**touches: tuple[list[str], list[str]]) -> Signals:
    return Signals(
        conflict_count=0,
        conflicted_files=[],
        file_overlap=[],
        symbol_overlap=[],
        diff_lines_merged=1,
        diff_lines_pr=1,
        touches={
            c: TouchInfo(merged=touches.get(c, ([], []))[0], pr=touches.get(c, ([], []))[1])
            for c in CATEGORIES
        },
    )


FORCED = PolicyResult(force_escalate=True, rules_hit=["migration:pr:migrations/0003_x.sql"])
CLEAR = PolicyResult(force_escalate=False, rules_hit=[])
CONFIDENCES = [0.0, 0.01, 0.5, 0.69, 0.7, 0.71, 0.99, 1.0, -1.0, 2.0, float("inf")]
FLOORS = [0.0, 0.5, 0.7, 1.0]


@pytest.mark.parametrize(
    "action,confidence,floor",
    list(itertools.product(["auto_rebase", "escalate"], CONFIDENCES, FLOORS)),
)
def test_policy_escalation_can_never_be_overridden(action, confidence, floor):
    decision = Decision(action=action, confidence=confidence, reasons=["r"])
    final = combine(decision, FORCED, confidence_floor=floor)
    assert final.action == "escalate"
    assert "policy" in final.escalated_by


@pytest.mark.parametrize("confidence,floor", list(itertools.product(CONFIDENCES, FLOORS)))
def test_orchestrator_escalate_always_escalates(confidence, floor):
    decision = Decision(action="escalate", confidence=confidence, reasons=["r"])
    assert combine(decision, CLEAR, confidence_floor=floor).escalated_by == ["orchestrator"]


@pytest.mark.parametrize("confidence,floor", list(itertools.product(CONFIDENCES, FLOORS)))
def test_auto_rebase_passes_only_at_or_above_floor(confidence, floor):
    final = combine(
        Decision(action="auto_rebase", confidence=confidence, reasons=["r"]),
        CLEAR,
        confidence_floor=floor,
    )
    if confidence >= floor:
        assert (final.action, final.escalated_by) == ("auto_rebase", [])
    else:
        assert (final.action, final.escalated_by) == ("escalate", ["confidence_floor"])


def test_floor_default_and_env_override(monkeypatch):
    low = Decision(action="auto_rebase", confidence=0.6, reasons=["r"])
    monkeypatch.delenv("REBASE_CONFIDENCE_FLOOR", raising=False)
    assert combine(low, CLEAR).confidence_floor == config.DEFAULT_CONFIDENCE_FLOOR == 0.7
    assert combine(low, CLEAR).action == "escalate"
    monkeypatch.setenv("REBASE_CONFIDENCE_FLOOR", "0")
    assert combine(low, CLEAR).action == "auto_rebase"


@pytest.mark.parametrize(
    "category,merged,pr,rule",
    [
        ("migration", ["migrations/0003_a.sql"], ["migrations/0003_b.sql"],
         "migration:pr+merged:migrations/0003_a.sql,migrations/0003_b.sql"),
        ("migration", [], ["migrations/0004_c.sql"], "migration:pr:migrations/0004_c.sql"),
        ("lockfile", ["uv.lock"], [], "lockfile:merged:uv.lock"),
        ("ci", [], [".github/workflows/ci.yml"], "ci:pr:.github/workflows/ci.yml"),
        ("auth", ["shop/auth/tokens.py"], [], "auth:merged:shop/auth/tokens.py"),
    ],
)  # fmt: skip
def test_each_forced_rule(category, merged, pr, rule):
    result = apply_policy(signals(**{category: (merged, pr)}))
    assert result.force_escalate is True
    assert result.rules_hit == [rule]


def test_config_is_reported_not_forced():
    result = apply_policy(signals(config=(["pyproject.toml"], [])))
    assert result.force_escalate is False
    assert result.rules_hit == []
    assert result.notes == ["config:merged:pyproject.toml"]


def test_no_touches_no_rules():
    result = apply_policy(signals())
    assert result == PolicyResult(force_escalate=False, rules_hit=[], notes=[])


def test_forced_categories_are_the_brief_list():
    assert set(config.FORCED_CATEGORIES) == {"migration", "lockfile", "ci", "auth"}
