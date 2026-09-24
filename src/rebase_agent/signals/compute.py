"""compute_signals(): all deterministic signals for one PR against one merged change."""

from pathlib import Path

from rebase_agent.git_ops import changed_files, diff_lines, merge_base, rev_parse
from rebase_agent.models import CATEGORIES, Signals, TouchInfo
from rebase_agent.signals.classify import classify
from rebase_agent.signals.conflicts import conflicted_files
from rebase_agent.signals.symbols import modified_symbols


def compute_signals(repo: Path, base: str, merged: str, pr_head: str) -> Signals:
    """Signals for rebasing pr_head onto merged.

    The merged change is base..merged (base is main before the push). The PR's own change is
    measured from its merge-base with base, so commits already on main aren't counted twice.
    """
    base, merged, pr_head = (rev_parse(repo, r) for r in (base, merged, pr_head))
    pr_base = merge_base(repo, base, pr_head)

    merged_files = changed_files(repo, base, merged)
    pr_files = changed_files(repo, pr_base, pr_head)
    conflicts = conflicted_files(repo, merged, pr_head)
    merged_cats = classify(merged_files)
    pr_cats = classify(pr_files)

    return Signals(
        conflict_count=len(conflicts),
        conflicted_files=conflicts,
        file_overlap=sorted(set(merged_files) & set(pr_files)),
        symbol_overlap=sorted(
            modified_symbols(repo, base, merged) & modified_symbols(repo, pr_base, pr_head)
        ),
        diff_lines_merged=diff_lines(repo, base, merged),
        diff_lines_pr=diff_lines(repo, pr_base, pr_head),
        touches={c: TouchInfo(merged=merged_cats[c], pr=pr_cats[c]) for c in CATEGORIES},
    )
