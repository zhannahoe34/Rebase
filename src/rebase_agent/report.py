"""RunOutcome -> markdown PR comment (D10: posted on every outcome)."""

from rebase_agent.models import RunOutcome

HEADLINE = {
    ("pushed", True): "Would rebase and push (dry run)",
    ("pushed", False): "Rebased and pushed",
    ("escalated", True): "Escalated to a human: not rebased",
    ("escalated", False): "Escalated to a human: not rebased",
    ("error", True): "Error: not rebased",
    ("error", False): "Error: not rebased",
}


def _details(summary: str, body: str) -> list[str]:
    return [
        "",
        "<details>",
        f"<summary>{summary}</summary>",
        "",
        "```",
        body.rstrip(),
        "```",
        "</details>",
    ]


def render(o: RunOutcome) -> str:
    lines = [
        f"### Auto-rebase: {HEADLINE[(o.final, o.dry_run)]}",
        "",
        (
            f"**Ended at:** `{o.stage}` · **cost:** ${o.cost.total_usd:.4f} · "
            f"**time:** {o.latency_s:.0f}s"
        ),
    ]
    if o.error:
        lines += ["", f"**{'Error' if o.final == 'error' else 'Reason'}:** {o.error}"]

    if o.decision:
        d = o.decision
        lines += [
            "",
            "#### Decision (before rebasing)",
            f"- Final: **{d.action}**"
            + (f" (escalated by: {', '.join(d.escalated_by)})" if d.escalated_by else ""),
            (
                f"- Orchestrator: {d.orchestrator.action}, "
                f"confidence {d.orchestrator.confidence:.2f} (floor {d.confidence_floor:.2f})"
            ),
            *[f"  - {r}" for r in d.orchestrator.reasons],
        ]
        if d.policy.rules_hit or d.policy.notes:
            lines += ["", "#### Policy"]
            lines += [f"- Rule hit (forces escalation): `{r}`" for r in d.policy.rules_hit]
            lines += [f"- Noted, not forced: `{n}`" for n in d.policy.notes]

    if o.signals:
        s = o.signals
        touched = [c for c, t in s.touches.items() if t.merged or t.pr]
        lines += [
            "",
            "#### Signals",
            "| Signal | Value |",
            "|---|---|",
            f"| Conflicts (dry-run merge) | {s.conflict_count}"
            + (f" ({', '.join(s.conflicted_files)})" if s.conflicted_files else "")
            + " |",
            f"| File overlap | {', '.join(s.file_overlap) or 'none'} |",
            f"| Symbol overlap | {', '.join(s.symbol_overlap) or 'none'} |",
            f"| Diff lines (merged / PR) | {s.diff_lines_merged} / {s.diff_lines_pr} |",
            f"| Risky categories touched | {', '.join(touched) or 'none'} |",
        ]

    if o.resolver:
        r = o.resolver
        lines += [
            "",
            "#### Resolver",
            f"- Status: **{r.status}**" + (f": {r.reason}" if r.reason else ""),
            f"- Turns: {r.turns} · cost ${r.cost_usd:.4f}"
            + (f" · files: {', '.join(r.files_touched)}" if r.files_touched else ""),
        ]
        if r.tool_calls:
            lines.append(f"- Tools used: {', '.join(dict.fromkeys(r.tool_calls))}")

    if o.verifier:
        v = o.verifier
        lines += [
            "",
            "#### Verifier",
            f"- Verdict: **{v.verdict}**",
            f"- Tests: {'passed' if v.tests_passed else 'FAILED'}",
            f"- Intent preserved: {'yes' if v.intent_preserved else 'NO'}",
            *[f"  - {r}" for r in v.intent_reasons],
        ]
        if not v.tests_passed:
            lines += _details("Test output (tail)", v.test_output_tail)

    if o.stale:
        st = o.stale
        lines += [
            "",
            "#### Stale-approval check",
            (
                "- PR patch unchanged by the rebase: yes"
                if st.unchanged
                else "- PR patch changed **only inside resolved conflicts** (allowed: "
                "review these lines)"
                if st.within_conflicts
                else "- PR patch unchanged by the rebase: NO"
            ),
            *[f"  - {r}" for r in st.reasons],
        ]
        lines += _details("git range-diff", st.range_diff or "(empty)")

    lines += ["", "#### Cost", "| Stage | USD |", "|---|---|"]
    lines += [f"| {k} | {v:.4f} |" for k, v in sorted(o.cost.per_stage_usd.items())]
    lines += [f"| **total** | **{o.cost.total_usd:.4f}** |"]
    return "\n".join(lines) + "\n"
