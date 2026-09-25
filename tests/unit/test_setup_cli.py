"""`rebase-agent setup --github-base`: which PRs make it into the workflow matrix."""

import json

import pytest
from typer.testing import CliRunner

from rebase_agent import cli
from rebase_agent.github_api import APPROVED_LABEL
from rebase_agent.models import PRSummary


class FakeGitHub:
    def __init__(self, prs: list[dict], approvals: dict[int, tuple[bool, str]]) -> None:
        self.prs, self.approvals, self.asked_base = prs, approvals, None

    def open_prs(self, base=None, head=None):
        self.asked_base = base
        return self.prs

    def eligibility(self, pr):
        return self.approvals[pr["number"]]


def pr(number: int, name: str) -> dict:
    return {"number": number, "head": {"ref": f"pr/{name}"}, "labels": [{"name": APPROVED_LABEL}]}


@pytest.fixture
def run_setup(tmp_path, monkeypatch):
    summaries = []

    def fake_summary(repo, base, merged, *, ledger):
        summaries.append((base, merged))
        return PRSummary(intent="i", touched_areas=[], behavior_changes=[], risk_notes=[])

    monkeypatch.setattr(cli, "summarize_merged", fake_summary)
    monkeypatch.setenv("SANDBOX_REPO_TOKEN", "tok")

    def run(fake: FakeGitHub):
        monkeypatch.setattr(cli, "GitHub", lambda *a, **k: fake)
        out, matrix = tmp_path / "out" / "summary.json", tmp_path / "out" / "prs.json"
        result = CliRunner().invoke(
            cli.app,
            [
                "setup", "--repo", str(tmp_path), "--base", "b", "--merged", "m",
                "--out", str(out), "--github-base", "main", "--matrix-out", str(matrix),
                "--run-dir", str(tmp_path / "run"),
            ],
        )  # fmt: skip
        assert result.exit_code == 0, result.output
        return result, out, matrix, summaries

    return run


def test_matrix_holds_only_eligible_prs_and_summary_is_computed_once(run_setup):
    fake = FakeGitHub(
        [pr(1, "trivial"), pr(2, "unapproved"), pr(3, "real_conflict")],
        {1: (True, "label"), 2: (False, "not approved"), 3: (True, "approved review")},
    )
    result, out, matrix, summaries = run_setup(fake)
    assert fake.asked_base == "main"
    assert json.loads(matrix.read_text()) == [1, 3]
    assert summaries == [("b", "m")]
    assert out.exists()
    assert "#2 pr/unapproved: skip (not approved)" in result.output


def test_no_eligible_prs_writes_an_empty_matrix_and_spends_nothing(run_setup):
    fake = FakeGitHub([pr(2, "unapproved")], {2: (False, "not approved")})
    result, out, matrix, summaries = run_setup(fake)
    assert json.loads(matrix.read_text()) == []
    assert summaries == []  # no LLM call
    assert not out.exists()
    assert "no eligible PRs" in result.output


def test_changes_requested_pr_is_excluded(run_setup):
    fake = FakeGitHub([pr(4, "x")], {4: (False, "changes requested")})
    _, _, matrix, summaries = run_setup(fake)
    assert json.loads(matrix.read_text()) == [] and summaries == []
