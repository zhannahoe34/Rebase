"""Range-diff parsing (Q4) on fixture outputs, plus real git end to end."""

from pathlib import Path

import pytest

from rebase_agent.resolver.agent import prepare_workdir
from rebase_agent.resolver.tools import Workdir
from rebase_agent.stale import parse_range_diff, stale_check

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("name", ["range_diff_context_only", "range_diff_message_changed"])
def test_context_and_message_changes_are_ignored(name):
    assert parse_range_diff((FIXTURES / f"{name}.txt").read_text()) == []


def test_identical_pairs_are_unchanged():
    assert parse_range_diff("1:  abc1234 = 1:  def5678 Add thing\n") == []


def test_changed_patch_line_is_reported():
    out = (
        "1:  abc1234 ! 1:  def5678 Reject empty item names in restock\n"
        "    @@ shop/inventory.py: def restock(...)\n"
        "    -+    if not item:\n"
        "    ++    if not item.strip():\n"
    )
    reasons = parse_range_diff(out)
    assert len(reasons) == 2
    assert "removed" in reasons[0] and "added" in reasons[1]


@pytest.mark.parametrize(
    "line,word", [("1:  abc1234 < -:  ------- Old commit\n", "dropped"),
                  ("-:  ------- > 1:  def5678 New commit\n", "added")],
)  # fmt: skip
def test_dropped_or_added_commits_are_changes(line, word):
    (reason,) = parse_range_diff(line)
    assert word in reason


def test_real_clean_rebase_is_unchanged(scenario_repos):
    refs = scenario_repos["trivial"]
    workdir, onto, head = prepare_workdir(Path(refs.repo), refs.main, refs.pr_branch)
    wd = Workdir(workdir)
    assert wd.git("rebase", onto).returncode == 0
    base = wd.git("merge-base", onto, head).stdout.strip()
    result = stale_check(workdir, base, head, onto, "HEAD")
    assert result.unchanged, result.reasons


def test_real_edited_patch_is_changed(scenario_repos):
    refs = scenario_repos["trivial"]
    workdir, onto, head = prepare_workdir(Path(refs.repo), refs.main, refs.pr_branch)
    wd = Workdir(workdir)
    assert wd.git("rebase", onto).returncode == 0
    changed = wd.git("show", "--name-only", "--format=", "HEAD").stdout.split()[0]
    (workdir / changed).write_text((workdir / changed).read_text() + "\n# extra\n")
    assert wd.git("commit", "-qam", "same subject", "--amend", "--no-edit").returncode == 0
    base = wd.git("merge-base", onto, head).stdout.strip()
    result = stale_check(workdir, base, head, onto, "HEAD")
    assert not result.unchanged
    assert any("# extra" in r for r in result.reasons)


def test_small_commit_with_rewritten_context_is_paired(tmp_path):
    """Seen live on the sandbox: two PRs appending to the same file and import line. With
    range-diff's default creation factor the tiny commit went unpaired ("dropped" +
    "added"); it must pair and name the changed line instead."""
    import subprocess

    def g(*a):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *a], capture_output=True, text=True, check=True
        ).stdout.strip()

    g("init", "-q", "-b", "main")
    g("config", "user.name", "t")
    g("config", "user.email", "t@t")
    (tmp_path / "m.py").write_text("from r import a\n\n\ndef x():\n    return 1\n")
    g("add", "."), g("commit", "-qm", "base")
    base = g("rev-parse", "HEAD")
    g("checkout", "-qb", "pr")
    (tmp_path / "m.py").write_text("from r import a, b\n\n\ndef x():\n    return 1\n")
    g("commit", "-qam", "Use b")
    old_head = g("rev-parse", "HEAD")
    g("checkout", "-q", "main")
    (tmp_path / "m.py").write_text("from r import a, c\n\n\ndef x():\n    return 2\n")
    g("commit", "-qam", "Use c")
    onto = g("rev-parse", "HEAD")
    g("checkout", "-q", "pr")
    subprocess.run(
        ["git", "-C", str(tmp_path), "rebase", "-q", onto], capture_output=True, check=False
    )
    (tmp_path / "m.py").write_text("from r import a, b, c\n\n\ndef x():\n    return 2\n")
    g("add", "m.py")
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "core.editor=true", "rebase", "--continue"],
        capture_output=True,
        check=True,
    )
    result = stale_check(tmp_path, base, old_head, onto, "HEAD")
    assert not result.unchanged
    assert not any("dropped" in r or "added by the rebase" in r for r in result.reasons)
    assert any("from r import a, b, c" in r for r in result.reasons)
