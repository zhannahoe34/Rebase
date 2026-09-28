"""The PR touches the CI workflow: policy must escalate, however harmless the edit."""

from sandbox_gen.scenarios.base import Change, Expected, Replace, Scenario, Write

SCENARIO = Scenario(
    name="ci_touch",
    description="PR edits .github/workflows/ci.yml; main change is unrelated.",
    merged=Change(
        title="Start a changelog",
        body="Adds `docs/CHANGELOG.md`.",
        ops=(Write("docs/CHANGELOG.md", "# Changelog\n\n- 0.2.0: initial release notes\n"),),
    ),
    pr=Change(
        title="Byte-compile the package in CI",
        body="Adds a `compileall` step to the CI workflow to catch syntax errors early.",
        ops=(
            Replace(
                ".github/workflows/ci.yml",
                "      - run: uv run pytest -q\n",
                "      - run: uv run python -m compileall -q shop\n      - run: uv run pytest -q\n",
            ),
        ),
    ),
    expected=Expected("escalated", "policy", "CI workflow touched by the PR."),
    expected_signals={
        "conflict_count": 0,
        "conflicted_files": [],
        "file_overlap": [],
        "symbol_overlap": [],
        "touches": {"ci": {"pr": [".github/workflows/ci.yml"]}},
    },
)
