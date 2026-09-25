"""Stale-approval check (D9, Q4): did rebasing change the PR's own patch?

"Unchanged" means every commit pairs up with its rebased copy and each pair has the
same added and removed lines. Context lines, hunk headers and commit messages are
ignored, so main's changes around the PR don't count. New, dropped or unpaired
commits count as changed.

Q4 option 2 (chosen 2026-09-25): a changed patch is still allowed when the change is
confined to resolved conflicts: every changed line is in a file that conflicted, and
every line that changed from the approved patch appeared inside a conflict hunk
(diff3 style, so the base side is included). The verifier must have passed first;
`run_pr` only gets here after it does. The comment lists every changed line.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from rebase_agent.git_ops import git
from rebase_agent.models import StaleCheckResult

_PAIR = re.compile(r"^\s*(?:\d+|-+):\s+(?:[0-9a-f]+|-+)\s+([=!<>])\s+(?:\d+|-+):\s+\S+\s?(.*)$")
_SECTION = re.compile(r"^ {4}[ +-] {1,2}## (.+?)(?: \((?:new|deleted)\))? ##$")
_HUNK_FILE = re.compile(r"^ {4}@@ ([^:]+?)(?::| *$)")
_MESSAGE_SECTIONS = ("Commit message", "Metadata")


@dataclass(frozen=True)
class PatchChange:
    kind: str  # "old" (line of the approved patch that changed) / "new" / "dropped" / "added"
    subject: str
    file: str | None = None
    line: str = ""  # the patch line, starting with + or -

    def reason(self) -> str:
        if self.kind == "dropped":
            return f"commit dropped by the rebase: {self.subject}"
        if self.kind == "added":
            return f"commit added by the rebase: {self.subject}"
        verb = "removed" if self.kind == "old" else "added"
        return f"patch line {verb} in '{self.subject}' ({self.file}): {self.line.strip()[:120]}"


def parse_changes(output: str) -> list[PatchChange]:
    changes: list[PatchChange] = []
    subject = ""
    file: str | None = None
    in_message = False
    for line in output.splitlines():
        pair = _PAIR.match(line)
        if pair:
            marker, subject = pair.groups()
            file, in_message = None, False
            if marker in "<>":
                changes.append(PatchChange("dropped" if marker == "<" else "added", subject))
            continue
        if not line.startswith("    ") or len(line) < 5:
            continue
        outer, inner = line[4], line[5:]
        if outer == "@":
            in_message = line.startswith("    @@ Metadata")
            hunk_file = _HUNK_FILE.match(line)
            if hunk_file and not in_message:
                file = hunk_file.group(1).strip()
            continue
        section = _SECTION.match(line)
        if section:
            name = section.group(1)
            in_message = name in _MESSAGE_SECTIONS
            if not in_message:
                file = name
            continue
        if in_message:
            continue
        if outer in "+-" and inner[:1] in ("+", "-"):
            changes.append(PatchChange("new" if outer == "+" else "old", subject, file, inner))
    return changes


def parse_range_diff(output: str) -> list[str]:
    """Reasons the patch changed; empty list means unchanged."""
    return [c.reason() for c in parse_changes(output)]


def within_conflicts(changes: list[PatchChange], conflicts: dict[str, list[str]]) -> bool:
    """Q4 option 2: every change is confined to lines that were in conflict."""
    if not changes or not conflicts:
        return False
    for c in changes:
        if c.kind in ("dropped", "added") or c.file not in conflicts:
            return False
        if c.kind == "old":
            text = c.line[1:]
            hunk_lines = {h for hunk in conflicts[c.file] for h in hunk.splitlines()}
            if text not in hunk_lines:
                return False
    return True


def stale_check(
    workdir: Path,
    old_base: str,
    old_head: str,
    new_base: str,
    new_head: str,
    *,
    conflicts: dict[str, list[str]] | None = None,
) -> StaleCheckResult:
    """`conflicts`: {file: [conflict hunks]} the resolver saw (empty for a clean rebase)."""
    out = git(
        Path(workdir),
        "range-diff",
        "--no-color",
        # Default 60 leaves small commits unpaired when their context changed a lot
        # (they show up as dropped + added). Pair as much as possible so the reasons
        # name the actual changed lines.
        "--creation-factor=100",
        f"{old_base}..{old_head}",
        f"{new_base}..{new_head}",
    ).stdout
    changes = parse_changes(out)
    return StaleCheckResult(
        unchanged=not changes,
        within_conflicts=within_conflicts(changes, conflicts or {}),
        range_diff=out,
        reasons=[c.reason() for c in changes],
    )
