"""Resolver (D7): rebase in a throwaway clone; on conflict, an Agent SDK loop resolves it.

The agent gets no built-in file/shell tools. It has only the workdir-scoped tools in
`tools.py`, our stdio MCP server (`conflict_preview`, `symbol_overlap`), and the
`rebase-playbook` skill. The clone has no remote, so nothing can be pushed from here.
Caps: max_turns and max_usd (SDK-enforced, also counted). Every failure returns
`escalated` or `error` with a reason; it never fails silently.
"""

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    ToolUseBlock,
    query,
)

from rebase_agent import config
from rebase_agent.config import Caps
from rebase_agent.git_ops import rev_parse
from rebase_agent.ledger import Ledger
from rebase_agent.models import PRSummary, ResolverResult
from rebase_agent.resolver.budget import Budget, usage_by_model
from rebase_agent.resolver.tools import Workdir, sdk_server

PLUGIN_DIR = Path(__file__).resolve().parent / "plugin"
SKILL = "rebase:rebase-playbook"
MCP_NAME = "rebase-tools"
IDENTITY = ("rebase-agent", "rebase-agent@users.noreply.github.com")

SYSTEM_PROMPT = """You resolve paused git rebases in a throwaway clone.
You have no shell and no general file tools: use only the tools you are given.
Load the rebase-playbook skill first and follow it exactly.
Resolving correctly or escalating with a reason are both acceptable outcomes;
guessing is not."""


def prepare_workdir(repo: Path, onto: str, head: str) -> tuple[Path, str, str]:
    """Clone repo into a fresh temp dir, branch `rebase-work` at head, no remote.

    Returns (workdir, onto_sha, head_sha); refs are resolved in the source repo because
    the clone keeps no remote-tracking refs once the remote is removed.
    """
    repo = Path(repo).resolve()
    onto_sha, head_sha = (rev_parse(repo, ref) for ref in (onto, head))
    workdir = Path(tempfile.mkdtemp(prefix="rebase-"))
    for cmd in (
        ["clone", "--quiet", "--no-checkout", str(repo), str(workdir)],
        ["-C", str(workdir), "checkout", "--quiet", "-B", "rebase-work", head_sha],
        ["-C", str(workdir), "remote", "remove", "origin"],
        ["-C", str(workdir), "config", "user.name", IDENTITY[0]],
        ["-C", str(workdir), "config", "user.email", IDENTITY[1]],
        # diff3 markers include the base side: more context for the agent, and the stale
        # check can tell which of the PR's original lines were inside a conflict.
        ["-C", str(workdir), "config", "merge.conflictStyle", "diff3"],
        ["-C", str(workdir), "cat-file", "-e", f"{onto_sha}^{{commit}}"],
    ):
        subprocess.run(["git", *cmd], capture_output=True, text=True, check=True)
    return workdir, onto_sha, head_sha


def _task(wd: Workdir, onto: str, head: str, pr: PRSummary) -> str:
    return f"""A rebase of the PR onto the newly merged main stopped on conflicts.

Workdir (repo_path for MCP tools): {wd.root}
onto (new main): {onto}
head (the PR before rebasing): {head}

PR intent: {pr.intent}
PR behavior changes: {"; ".join(pr.behavior_changes) or "none"}

Currently: {wd.list_conflicts()}

Resolve the rebase following the rebase-playbook skill, or escalate."""


def _options(wd: Workdir, caps: Caps, model: str) -> ClaudeAgentOptions:
    server, tool_names = sdk_server(wd)
    mcp_tools = [f"mcp__{MCP_NAME}__conflict_preview", f"mcp__{MCP_NAME}__symbol_overlap"]
    return ClaudeAgentOptions(
        tools=["Skill"],  # the only built-in; no Bash/Read/Write/Edit
        allowed_tools=[*tool_names, *mcp_tools],
        mcp_servers={
            "rebase": server,
            MCP_NAME: {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "rebase_agent.mcp_server.server", str(wd.root)],
            },
        },
        plugins=[{"type": "local", "path": str(PLUGIN_DIR)}],
        skills=[SKILL],
        setting_sources=[],  # ignore user/project settings on this machine
        permission_mode="dontAsk",
        system_prompt=SYSTEM_PROMPT,
        max_turns=caps.max_turns,
        max_budget_usd=caps.max_usd,
        model=model,
        cwd=str(wd.root),
        env={"ANTHROPIC_API_KEY": config.api_key()},
    )


async def resolve(
    workdir: Path,
    onto: str,
    pr: PRSummary,
    caps: Caps,
    *,
    model: str,
    ledger: Ledger | None = None,
    pr_ref: str | None = None,
) -> ResolverResult:
    wd = Workdir(workdir)
    head = wd.git("rev-parse", "HEAD").stdout.strip()
    rebase = wd.git("rebase", onto)
    if rebase.returncode == 0:
        return ResolverResult(
            status="clean",
            reason=None,
            turns=0,
            cost_usd=0.0,
            files_touched=[],
            head_sha=wd.git("rev-parse", "HEAD").stdout.strip(),
        )
    if not wd.rebase_in_progress():
        return _fail(wd, "error", f"git rebase failed: {rebase.stderr.strip()[-500:]}", 0, 0.0)

    wd.record_conflicts()
    budget = Budget(caps)
    result: ResultMessage | None = None
    start = time.monotonic()
    error: str | None = None
    try:
        async for message in query(
            prompt=_task(wd, onto, head, pr), options=_options(wd, caps, model)
        ):
            if isinstance(message, AssistantMessage):
                budget.observe_assistant(message.message_id)
                wd.tool_calls += [b.name for b in message.content if isinstance(b, ToolUseBlock)]
            elif isinstance(message, ResultMessage):
                result = message
            if budget.over_turns():
                break
    except Exception as e:  # noqa: BLE001 - any SDK/CLI failure becomes a reported error
        if result is None:
            error = f"{type(e).__name__}: {e}"[:500]
    latency = time.monotonic() - start

    cost = (result.total_cost_usd or 0.0) if result else 0.0
    turns = result.num_turns if result else budget.turns
    if ledger is not None and result is not None:
        per_model = usage_by_model(result.model_usage, result.usage)
        for m, (usage, reported) in per_model.items():
            ledger.record(
                stage="resolver",
                model=m,
                usage=usage,
                latency_s=latency / max(len(per_model), 1),
                pr=pr_ref,
                reported_cost_usd=reported,
            )

    if error is not None:
        return _fail(wd, "error", error, turns, cost)
    cap = budget.over_turns() or budget.result_reason(result.subtype if result else None, cost)
    if cap:
        return _fail(wd, "escalated", cap, turns, cost)
    if wd.escalation:
        return _fail(wd, "escalated", wd.escalation, turns, cost)
    if result is None or result.is_error:
        detail = result.subtype if result else "no result message"
        return _fail(wd, "error", f"agent run failed: {detail}", turns, cost)
    if wd.rebase_in_progress() or wd.conflicted():
        return _fail(wd, "escalated", "agent stopped before the rebase finished", turns, cost)
    return ResolverResult(
        status="resolved",
        reason=None,
        turns=turns,
        cost_usd=cost,
        files_touched=sorted(wd.files_touched),
        head_sha=wd.git("rev-parse", "HEAD").stdout.strip(),
        tool_calls=wd.tool_calls,
        conflict_hunks=wd.conflict_hunks,
    )


def _fail(wd: Workdir, status: str, reason: str, turns: int, cost: float) -> ResolverResult:
    if wd.rebase_in_progress():
        wd.git("rebase", "--abort")
    return ResolverResult(
        status=status,
        reason=reason,
        turns=turns,
        cost_usd=cost,
        files_touched=sorted(wd.files_touched),
        head_sha=None,
        tool_calls=wd.tool_calls,
        conflict_hunks=wd.conflict_hunks,
    )


def cleanup(workdir: Path) -> None:
    shutil.rmtree(workdir, ignore_errors=True)
