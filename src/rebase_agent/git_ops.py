"""Thin subprocess wrappers around git. All functions take the repo path explicitly."""

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc


def rev_parse(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").stdout.strip()


def merge_base(repo: Path, a: str, b: str) -> str:
    return git(repo, "merge-base", a, b).stdout.strip()


def changed_files(repo: Path, old: str, new: str) -> list[str]:
    out = git(repo, "diff", "--name-only", "--no-renames", old, new).stdout
    return sorted(line for line in out.splitlines() if line)


def diff_lines(repo: Path, old: str, new: str) -> int:
    """Added + deleted lines (binary files count as 0)."""
    total = 0
    for line in git(repo, "diff", "--numstat", "--no-renames", old, new).stdout.splitlines():
        added, deleted, _ = line.split("\t", 2)
        if added != "-":
            total += int(added) + int(deleted)
    return total


def show_file(repo: Path, rev: str, path: str) -> str | None:
    """File content at rev, or None if it doesn't exist there."""
    proc = git(repo, "show", f"{rev}:{path}", check=False)
    return proc.stdout if proc.returncode == 0 else None


def unified_diff(repo: Path, old: str, new: str, path: str) -> str:
    return git(repo, "diff", "-U0", "--no-renames", old, new, "--", path).stdout
