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


def conflict_hunks(repo: Path, onto: str, head: str) -> dict[str, list[str]]:
    """Conflict-marker regions per conflicted file, from merge-tree's result tree.

    Each hunk runs from a `<<<<<<<` line to its `>>>>>>>` line inclusive. Files that
    conflict without markers (e.g. modify/delete) map to an empty list.
    """
    proc = git(repo, "merge-tree", "--write-tree", "--no-messages", onto, head, check=False)
    if proc.returncode == 0:
        return {}
    if proc.returncode != 1:
        raise GitError(f"git merge-tree failed ({proc.returncode}): {proc.stderr.strip()}")
    lines = proc.stdout.splitlines()
    tree = lines[0]
    paths = sorted({line.split("\t", 1)[1] for line in lines[1:] if "\t" in line})
    result: dict[str, list[str]] = {}
    for path in paths:
        content = git(repo, "show", f"{tree}:{path}", check=False).stdout
        hunks: list[str] = []
        current: list[str] | None = None
        for line in content.splitlines():
            if line.startswith("<<<<<<<"):
                current = [line]
            elif current is not None:
                current.append(line)
                if line.startswith(">>>>>>>"):
                    hunks.append("\n".join(current))
                    current = None
        result[path] = hunks
    return result
