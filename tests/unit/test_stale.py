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
