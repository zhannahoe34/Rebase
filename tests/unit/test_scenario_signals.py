from pathlib import Path

import pytest

from rebase_agent.models import CATEGORIES
from rebase_agent.signals import compute_signals
from sandbox_gen.scenarios import SCENARIOS


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_signals_match_expected(name, scenario_repos):
    refs = scenario_repos[name]
    expected = SCENARIOS[name].expected_signals
    signals = compute_signals(Path(refs.repo), refs.base, refs.main, refs.pr_branch)

    for field in ("conflict_count", "conflicted_files", "file_overlap", "symbol_overlap"):
        assert getattr(signals, field) == expected[field], field
    for cat in CATEGORIES:
        want = expected["touches"].get(cat, {})
        got = signals.touches[cat]
        assert got.merged == want.get("merged", []), (cat, "merged")
        assert got.pr == want.get("pr", []), (cat, "pr")
    assert signals.diff_lines_merged > 0
    assert signals.diff_lines_pr > 0


def test_signals_accept_shas_and_refs_equally(scenario_repos):
    refs = scenario_repos["real_conflict"]
    by_ref = compute_signals(Path(refs.repo), "base", "main", refs.pr_branch)
    by_sha = compute_signals(Path(refs.repo), refs.base, refs.main, refs.pr_head)
    assert by_ref == by_sha
