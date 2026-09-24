import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sandbox_gen.generator import Refs, build_local
from sandbox_gen.scenarios import SCENARIOS

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def scenario_repos(tmp_path_factory) -> dict[str, Refs]:
    root = tmp_path_factory.mktemp("scenarios")
    return {name: build_local(root / name, s) for name, s in SCENARIOS.items()}


@pytest.fixture(scope="session")
def llm_run_dir() -> Path:
    """One run dir for the whole session, so `rebase-agent costs <dir>` gives its total."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(os.environ.get("REBASE_TEST_RUN_DIR") or ROOT / "runs" / f"pytest-{stamp}")
