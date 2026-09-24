"""Dry-run merge via `git merge-tree --write-tree` (no worktree, no index changes)."""

from pathlib import Path

from rebase_agent.git_ops import GitError, git


def conflicted_files(repo: Path, merged: str, pr_head: str) -> list[str]:
    proc = git(
        repo,
        "merge-tree",
        "--write-tree",
        "--name-only",
        "--no-messages",
        merged,
        pr_head,
        check=False,
    )
    if proc.returncode == 0:
        return []
    if proc.returncode != 1:
        raise GitError(f"git merge-tree failed ({proc.returncode}): {proc.stderr.strip()}")
    # First line is the (partial) tree OID; the rest are conflicted paths.
    return sorted({line for line in proc.stdout.splitlines()[1:] if line})
