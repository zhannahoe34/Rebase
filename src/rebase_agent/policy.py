"""Policy guardrails (D6): hard rules in plain code, outside the LLM.

The LLM can escalate more often than policy, never less: `combine` returns escalate
whenever policy forces it, whatever the orchestrator says.
"""

from rebase_agent import config
from rebase_agent.models import Decision, FinalDecision, PolicyResult, Signals


def _rule(category: str, merged: list[str], pr: list[str]) -> str | None:
    sides = [side for side, paths in (("pr", pr), ("merged", merged)) if paths]
    if not sides:
        return None
    paths = sorted(set(merged) | set(pr))
    return f"{category}:{'+'.join(sides)}:{','.join(paths)}"


def apply_policy(signals: Signals) -> PolicyResult:
    """Force escalation if either side touches a forced category (migration, lockfile, ci,
    auth). Config files are reported in notes but don't force escalation (Q11)."""
    rules_hit: list[str] = []
    notes: list[str] = []
    for category, touch in sorted(signals.touches.items()):
        rule = _rule(category, touch.merged, touch.pr)
        if rule is None:
            continue
        if category in config.FORCED_CATEGORIES:
            rules_hit.append(rule)
        else:
            notes.append(rule)
    return PolicyResult(force_escalate=bool(rules_hit), rules_hit=rules_hit, notes=notes)


def combine(
    decision: Decision, policy: PolicyResult, *, confidence_floor: float | None = None
) -> FinalDecision:
    """Pure. Escalate if policy forces it, the orchestrator says so, or an auto_rebase is
    below the confidence floor (Q6, still open; set REBASE_CONFIDENCE_FLOOR=0 to disable)."""
    floor = config.confidence_floor() if confidence_floor is None else confidence_floor
    escalated_by: list[str] = []
    if policy.force_escalate:
        escalated_by.append("policy")
    if decision.action == "escalate":
        escalated_by.append("orchestrator")
    elif decision.confidence < floor:
        escalated_by.append("confidence_floor")
    return FinalDecision(
        action="escalate" if escalated_by else "auto_rebase",
        orchestrator=decision,
        policy=policy,
        escalated_by=escalated_by,
        confidence_floor=floor,
    )
