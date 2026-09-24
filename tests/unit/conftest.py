import os
import subprocess
import sys
from pathlib import Path

import pytest

from sandbox_gen.generator import Refs, build_local
from sandbox_gen.scenarios import SCENARIOS

GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, env=GIT_ENV, check=check
    )


def run_sandbox_tests(repo: Path) -> subprocess.CompletedProcess[str]:
    """Run the sandbox's own pytest suite with this interpreter (no network needed)."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def scenario_repos(tmp_path_factory) -> dict[str, Refs]:
    root = tmp_path_factory.mktemp("scenarios")
    return {name: build_local(root / name, s) for name, s in SCENARIOS.items()}
