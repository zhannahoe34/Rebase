"""MCP server tools, called through real MCP client sessions (in-process and stdio)."""

import sys
from pathlib import Path

import anyio
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

from rebase_agent.mcp_server.server import build_server


def call(server_or_params, tool: str, args: dict):
    async def go():
        async with Client(server_or_params) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert names == {"conflict_preview", "symbol_overlap"}
            return await client.call_tool(tool, args)

    return anyio.run(go)


def test_conflict_preview_real_conflict(scenario_repos):
    refs = scenario_repos["real_conflict"]
    root = Path(refs.repo).parent
    result = call(
        build_server(root),
        "conflict_preview",
        {"repo_path": refs.repo, "onto": refs.main, "head": refs.pr_head},
    )
    assert not result.is_error
    assert result.structured_content["conflicted_files"] == ["shop/inventory.py"]
    hunks = result.structured_content["hunks"]["shop/inventory.py"]
    assert len(hunks) == 1
    assert hunks[0].startswith("<<<<<<<") and hunks[0].splitlines()[-1].startswith(">>>>>>>")
    assert "=======" in hunks[0]


def test_conflict_preview_clean(scenario_repos):
    refs = scenario_repos["trivial"]
    result = call(
        build_server(Path(refs.repo).parent),
        "conflict_preview",
        {"repo_path": refs.repo, "onto": refs.main, "head": refs.pr_head},
    )
    assert result.structured_content == {"conflicted_files": [], "hunks": {}}


def test_symbol_overlap(scenario_repos):
    refs = scenario_repos["real_conflict"]
    result = call(
        build_server(Path(refs.repo).parent),
        "symbol_overlap",
        {"repo_path": refs.repo, "base": refs.base, "a": refs.main, "b": refs.pr_head},
    )
    assert result.structured_content["result"] == ["shop/inventory.py:restock"]


@pytest.mark.parametrize(
    "args",
    [
        {"repo_path": "/etc", "onto": "main", "head": "HEAD"},
        {"repo_path": "{repo}/../..", "onto": "main", "head": "HEAD"},
        {"repo_path": "{repo}", "onto": "--output=/tmp/x", "head": "HEAD"},
    ],
)
def test_rejects_paths_outside_root_and_option_refs(scenario_repos, args):
    refs = scenario_repos["trivial"]
    args = {k: v.format(repo=refs.repo) for k, v in args.items()}
    result = call(build_server(Path(refs.repo)), "conflict_preview", args)
    assert result.is_error


def test_stdio_transport(scenario_repos):
    refs = scenario_repos["real_conflict"]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "rebase_agent.mcp_server.server", str(Path(refs.repo).parent)],
    )
    result = call(
        params,
        "symbol_overlap",
        {"repo_path": refs.repo, "base": refs.base, "a": refs.main, "b": refs.pr_head},
    )
    assert result.structured_content["result"] == ["shop/inventory.py:restock"]
