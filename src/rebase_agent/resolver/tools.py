"""Resolver tools, scoped to one throwaway workdir (D7).

Every path is resolved and must stay inside the workdir, outside `.git`. Writes are
limited to files git currently reports as conflicted. There is no push or remote tool,
and the clone has no remote. `Workdir` is plain Python so it can be tested without an
LLM; `sdk_server()` wraps it as in-process tools for the Agent SDK.
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from claude_agent_sdk import create_sdk_mcp_server, tool

TEST_TIMEOUT_S = 300
OUTPUT_TAIL = 3000


class ToolError(ValueError):
    pass


def _git_env() -> dict[str, str]:
    return {**os.environ, "GIT_EDITOR": "true", "GIT_TERMINAL_PROMPT": "0"}


def run_pytest(root: Path) -> tuple[bool, str]:
    """Run the repo's pytest suite with this interpreter. (passed, output tail)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"tests timed out after {TEST_TIMEOUT_S}s"
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-OUTPUT_TAIL:]


class Workdir:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.escalation: str | None = None
        self.files_touched: set[str] = set()
        self.tool_calls: list[str] = []  # names, in call order (filled by the agent loop)
        self.conflict_hunks: dict[str, list[str]] = {}  # every conflict seen, per file

    # --- helpers -------------------------------------------------------------------
    def path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not p.is_relative_to(self.root):
            raise ToolError(f"{rel}: outside the workdir")
        if ".git" in p.relative_to(self.root).parts:
            raise ToolError(f"{rel}: .git is off limits")
        return p

    def git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            env=_git_env(),
            check=False,
        )

    def conflicted(self) -> list[str]:
        out = self.git("diff", "--name-only", "--diff-filter=U").stdout
        return sorted(line for line in out.splitlines() if line)

    def record_conflicts(self) -> None:
        """Remember the marker regions of every currently conflicted file."""
        for rel in self.conflicted():
            hunks, current = self.conflict_hunks.setdefault(rel, []), None
            path = self.root / rel
            for line in path.read_text().splitlines() if path.is_file() else []:
                if line.startswith("<<<<<<<"):
                    current = [line]
                elif current is not None:
                    current.append(line)
                    if line.startswith(">>>>>>>"):
                        hunks.append("\n".join(current))
                        current = None

    def rebase_in_progress(self) -> bool:
        git_dir = self.root / ".git"
        return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()

    # --- tools ---------------------------------------------------------------------
    def read_file(self, path: str) -> str:
        p = self.path(path)
        if not p.is_file():
            raise ToolError(f"{path}: no such file")
        return p.read_text()

    def write_file(self, path: str, content: str) -> str:
        p = self.path(path)
        rel = p.relative_to(self.root).as_posix()
        if rel not in self.conflicted():
            raise ToolError(f"{rel}: not a conflicted file; only conflicted files may be written")
        p.write_text(content)
        self.files_touched.add(rel)
        return f"wrote {rel} ({len(content)} chars)"

    def list_conflicts(self) -> str:
        files = self.conflicted()
        if not files:
            state = "rebase in progress" if self.rebase_in_progress() else "no rebase in progress"
            return f"no conflicted files ({state})"
        return "conflicted files:\n" + "\n".join(files)

    def run_tests(self) -> str:
        passed, tail = run_pytest(self.root)
        return f"{'PASSED' if passed else 'FAILED'}\n{tail}"

    def git_add(self, path: str) -> str:
        p = self.path(path)
        rel = p.relative_to(self.root).as_posix()
        if rel not in self.conflicted():
            raise ToolError(f"{rel}: not a conflicted file")
        markers = ("<<<<<<<", "|||||||", ">>>>>>>")
        if any(line.startswith(markers) for line in p.read_text().splitlines()):
            raise ToolError(f"{rel}: conflict markers remain")
        proc = self.git("add", "--", rel)
        if proc.returncode != 0:
            raise ToolError(proc.stderr.strip())
        return f"staged {rel}"

    def rebase_continue(self) -> str:
        if not self.rebase_in_progress():
            return "no rebase in progress; nothing to continue"
        if self.conflicted():
            raise ToolError("unresolved files remain: " + ", ".join(self.conflicted()))
        proc = self.git("rebase", "--continue")
        out = (proc.stdout + proc.stderr).strip()[-OUTPUT_TAIL:]
        if proc.returncode == 0 and not self.rebase_in_progress():
            return f"rebase complete\n{out}"
        self.record_conflicts()
        return f"rebase stopped again\n{out}\n{self.list_conflicts()}"

    def escalate(self, reason: str) -> str:
        self.escalation = reason.strip() or "escalated without a reason"
        return "escalation recorded; stop now"


def _text(fn, *args: Any) -> dict[str, Any]:
    try:
        return {"content": [{"type": "text", "text": fn(*args)}]}
    except ToolError as e:
        return {"content": [{"type": "text", "text": f"error: {e}"}], "is_error": True}


SERVER_NAME = "rebase"


def sdk_server(wd: Workdir):
    """In-process SDK MCP server exposing the Workdir tools."""

    @tool("read_file", "Read a file in the workdir (path relative to it).", {"path": str})
    async def read_file(a):
        return _text(wd.read_file, a["path"])

    @tool(
        "write_file",
        "Overwrite a conflicted file with its full resolved content.",
        {"path": str, "content": str},
    )
    async def write_file(a):
        return _text(wd.write_file, a["path"], a["content"])

    @tool("list_conflicts", "List files git reports as conflicted right now.", {})
    async def list_conflicts(a):
        return _text(wd.list_conflicts)

    @tool("run_tests", "Run the project's test suite in the workdir.", {})
    async def run_tests(a):
        return _text(wd.run_tests)

    @tool("git_add", "Stage a resolved file (refused if markers remain).", {"path": str})
    async def git_add(a):
        return _text(wd.git_add, a["path"])

    @tool("rebase_continue", "Continue the rebase once every conflict is staged.", {})
    async def rebase_continue(a):
        return _text(wd.rebase_continue)

    @tool(
        "escalate", "Give up and hand the PR to a human, with a specific reason.", {"reason": str}
    )
    async def escalate(a):
        return _text(wd.escalate, a["reason"])

    tools = [read_file, write_file, list_conflicts, run_tests, git_add, rebase_continue, escalate]
    return create_sdk_mcp_server(SERVER_NAME, tools=tools), [
        f"mcp__{SERVER_NAME}__{t.name}" for t in tools
    ]
