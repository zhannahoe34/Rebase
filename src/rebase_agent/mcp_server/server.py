"""Our stdio MCP server (D11): conflict_preview and symbol_overlap for the resolver.

Every repo path must resolve inside the root given at startup (the resolver's workdir),
and refs may not look like git options.

Run: python -m rebase_agent.mcp_server.server ROOT
"""

import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

from rebase_agent.signals.conflicts import conflict_hunks
from rebase_agent.signals.symbols import modified_symbols


class ConflictPreview(BaseModel):
    conflicted_files: list[str]
    hunks: dict[str, list[str]]


class PathOutsideRoot(ValueError):
    pass


def _repo(root: Path, repo_path: str) -> Path:
    path = Path(repo_path).resolve()
    if not path.is_relative_to(root):
        raise PathOutsideRoot(f"{repo_path} is outside the allowed root {root}")
    return path


def _ref(ref: str) -> str:
    if not ref or ref.startswith("-"):
        raise ValueError(f"invalid ref {ref!r}")
    return ref


def build_server(root: Path) -> MCPServer:
    root = root.resolve()
    server = MCPServer(
        name="rebase-tools",
        instructions="Read-only git analysis for resolving a rebase inside the workdir.",
    )

    @server.tool()
    def conflict_preview(repo_path: str, onto: str, head: str) -> ConflictPreview:
        """Dry-run merge of HEAD onto ONTO. Returns conflicted_files and, per file, the
        conflict hunks with standard <<<<<<< / ======= / >>>>>>> markers."""
        hunks = conflict_hunks(_repo(root, repo_path), _ref(onto), _ref(head))
        return ConflictPreview(conflicted_files=sorted(hunks), hunks=hunks)

    @server.tool()
    def symbol_overlap(repo_path: str, base: str, a: str, b: str) -> list[str]:
        """`path:qualname` of functions/classes modified both in base..a and in base..b."""
        repo = _repo(root, repo_path)
        both = modified_symbols(repo, _ref(base), _ref(a)) & modified_symbols(
            repo, _ref(base), _ref(b)
        )
        return sorted(both)

    return server


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: python -m rebase_agent.mcp_server.server ROOT")
    build_server(Path(sys.argv[1])).run("stdio")


if __name__ == "__main__":
    main()
