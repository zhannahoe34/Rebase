"""Stale-approval check (D9, Q4): did rebasing change the PR's own patch?

"Unchanged" means every commit pairs up with its rebased copy and each pair has the
same added and removed lines. Context lines, hunk headers and commit messages are
ignored, so main's changes around the PR don't count. New, dropped or unpaired
commits count as changed.
"""

import re
from pathlib import Path

from rebase_agent.git_ops import git
from rebase_agent.models import StaleCheckResult

_PAIR = re.compile(r"^\s*(?:\d+|-+):\s+(?:[0-9a-f]+|-+)\s+([=!<>])\s+(?:\d+|-+):\s+\S+\s?(.*)$")
_SECTION = re.compile(r"^ {4}[ +-] {1,2}## (.+) ##$")


def parse_range_diff(output: str) -> list[str]:
    """Reasons the patch changed; empty list means unchanged."""
    reasons: list[str] = []
    subject = ""
    in_message = False
    for line in output.splitlines():
        pair = _PAIR.match(line)
        if pair:
            marker, subject = pair.groups()
            in_message = False
            if marker == "<":
                reasons.append(f"commit dropped by the rebase: {subject}")
            elif marker == ">":
                reasons.append(f"commit added by the rebase: {subject}")
            continue
        if not line.startswith("    ") or len(line) < 5:
            continue
        outer, inner = line[4], line[5:]
        if outer == "@":
            in_message = line.startswith("    @@ Metadata")
            continue
        section = _SECTION.match(line)
        if section:
            in_message = section.group(1) in ("Commit message", "Metadata")
            continue
        if in_message:
            continue
        if outer in "+-" and inner[:1] in ("+", "-"):
            reasons.append(
                f"patch line {'added' if outer == '+' else 'removed'} in "
                f"'{subject}': {inner.strip()[:120]}"
            )
    return reasons


def stale_check(
    workdir: Path, old_base: str, old_head: str, new_base: str, new_head: str
) -> StaleCheckResult:
    out = git(
        Path(workdir),
        "range-diff",
        "--no-color",
        f"{old_base}..{old_head}",
        f"{new_base}..{new_head}",
    ).stdout
    reasons = parse_range_diff(out)
    return StaleCheckResult(unchanged=not reasons, range_diff=out, reasons=reasons)
