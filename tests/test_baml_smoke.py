"""Phase 1 step 1: prove the pinned BAML toolchain works in this environment.

Covers: CLI version matches the pin, generation succeeds, the generated client
imports, runtime model selection and usage collection exist, and the Anthropic
request builds offline. The live call runs only with REBASE_ANTHROPIC_API_KEY set.
"""

import os
import subprocess
from importlib.metadata import version
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PINNED = "0.226.2"


def test_cli_version_matches_pin():
    out = subprocess.run(
        ["baml-cli", "--version"], capture_output=True, text=True, check=True
    ).stdout
    assert PINNED in out
    assert version("baml-py") == PINNED


def test_generate_writes_python_client():
    subprocess.run(["baml-cli", "generate"], cwd=ROOT, check=True, capture_output=True)
    assert (ROOT / "src/rebase_agent/baml_client/sync_client.py").is_file()


def test_generated_client_imports_and_builds_request():
    from rebase_agent.baml_client import b
    from rebase_agent.baml_client.types import SmokeResult

    assert SmokeResult(ok=True, echo="x").echo == "x"
    req = b.request.Smoke("hello")
    assert req.url == "https://api.anthropic.com/v1/messages"
    assert req.body.json()["model"] == "claude-haiku-4-5-20251001"


def test_runtime_model_override_and_collector():
    from baml_py import ClientRegistry, Collector

    from rebase_agent.baml_client import b

    registry = ClientRegistry()
    registry.add_llm_client(
        name="Override",
        provider="anthropic",
        options={"model": "claude-sonnet-5", "api_key": "test-key"},
    )
    registry.set_primary("Override")
    req = b.with_options(client_registry=registry, collector=Collector(name="smoke")).request.Smoke(
        "hi"
    )
    assert req.body.json()["model"] == "claude-sonnet-5"
    assert req.headers["x-api-key"] == "test-key"


@pytest.mark.llm
@pytest.mark.skipif(
    not os.environ.get("REBASE_ANTHROPIC_API_KEY"),
    reason="REBASE_ANTHROPIC_API_KEY not set: live call NOT RUN",
)
def test_live_call():
    from baml_py import Collector

    from rebase_agent.baml_client import b

    collector = Collector(name="smoke")
    result = b.with_options(collector=collector).Smoke("hello")
    assert result.ok is True
    assert result.echo == "hello"
    assert collector.last is not None and collector.last.usage.input_tokens > 0
