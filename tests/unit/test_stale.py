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


def _conflicting_rebase(tmp_path, *, extra_pr_edit: bool = False):
    """PR and main both edit the same import line; resolve by keeping both. Returns
    (workdir, base, old_head, onto, conflicts seen)."""
    from rebase_agent.resolver.tools import Workdir

    wd = Workdir(tmp_path)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.name", "t"),
        ("config", "user.email", "t@t"),
        ("config", "merge.conflictStyle", "diff3"),
    ):
        wd.git(*args)
    body = "\n\ndef x():\n    return {}\n\n\ndef y():\n    return {}\n"
    (tmp_path / "m.py").write_text("from r import a" + body.format(1, 1))
    wd.git("add", "."), wd.git("commit", "-qm", "base")
    base = wd.git("rev-parse", "HEAD").stdout.strip()
    wd.git("checkout", "-qb", "pr")
    pr_body = body.format(1, 9 if extra_pr_edit else 1)
    (tmp_path / "m.py").write_text("from r import a, b" + pr_body)
    wd.git("commit", "-qam", "Use b")
    old_head = wd.git("rev-parse", "HEAD").stdout.strip()
    wd.git("checkout", "-q", "main")
    (tmp_path / "m.py").write_text("from r import a, c" + body.format(2, 1))
    wd.git("commit", "-qam", "Use c")
    onto = wd.git("rev-parse", "HEAD").stdout.strip()
    wd.git("checkout", "-q", "pr")
    assert wd.git("rebase", onto).returncode != 0
    wd.record_conflicts()
    resolved = "from r import a, b, c" + body.format(2, 9 if extra_pr_edit else 1)
    (tmp_path / "m.py").write_text(resolved)
    wd.git("add", "m.py")
    assert wd.git("rebase", "--continue").returncode == 0
    return tmp_path, base, old_head, onto, wd.conflict_hunks


def test_small_commit_with_rewritten_context_is_paired(tmp_path):
    """Seen live on the sandbox (PR #15): with range-diff's default creation factor the
    tiny commit went unpaired ("dropped" + "added"); it must pair and name the line."""
    workdir, base, old_head, onto, _ = _conflicting_rebase(tmp_path)
    result = stale_check(workdir, base, old_head, onto, "HEAD")
    assert not result.unchanged
    assert not any("dropped" in r or "added by the rebase" in r for r in result.reasons)
    assert any("from r import a, b, c" in r for r in result.reasons)


def test_change_confined_to_resolved_conflict_is_allowed(tmp_path):
    """Q4 option 2: the PR's import line had to change to keep both sides."""
    workdir, base, old_head, onto, conflicts = _conflicting_rebase(tmp_path)
    assert list(conflicts) == ["m.py"] and "|||||||" in conflicts["m.py"][0]  # diff3
    result = stale_check(workdir, base, old_head, onto, "HEAD", conflicts=conflicts)
    assert not result.unchanged
    assert result.within_conflicts


def test_change_outside_the_conflict_still_escalates(tmp_path):
    """Same conflict, but the rebased patch also differs in y() (not in any hunk)."""
    workdir, base, old_head, onto, conflicts = _conflicting_rebase(tmp_path, extra_pr_edit=True)
    wd_file = workdir / "m.py"
    wd_file.write_text(wd_file.read_text().replace("return 9", "return 8"))
    from rebase_agent.resolver.tools import Workdir

    Workdir(workdir).git("commit", "-qa", "--amend", "--no-edit")
    result = stale_check(workdir, base, old_head, onto, "HEAD", conflicts=conflicts)
    assert not result.unchanged
    assert not result.within_conflicts


def test_no_conflicts_means_no_allowance(tmp_path):
    workdir, base, old_head, onto, _ = _conflicting_rebase(tmp_path)
    assert not stale_check(workdir, base, old_head, onto, "HEAD", conflicts={}).within_conflicts
