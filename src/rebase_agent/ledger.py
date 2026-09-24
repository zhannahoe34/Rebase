"""Cost ledger (PLAN.md §0.6): one JSONL row per model call, plus rollups."""

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from rebase_agent import config
from rebase_agent.models import LedgerRow, Usage

LEDGER_NAME = "ledger.jsonl"


def cost_usd(model: str, usage: Usage) -> tuple[float, dict[str, float]]:
    """Estimated cost from tokens x the price table. Unknown model is an error, never $0."""
    price = config.PRICES.get(model)
    if price is None:
        raise KeyError(f"model {model!r} has no entry in config.PRICES")
    rates = {
        "input": price.input,
        "output": price.output,
        "cache_read": price.cache_read,
        "cache_write": price.cache_write,
    }
    cost = (
        usage.input_tokens * price.input
        + usage.output_tokens * price.output
        + usage.cache_read_tokens * price.cache_read
        + usage.cache_write_tokens * price.cache_write
    ) / 1_000_000
    return cost, rates


class Ledger:
    """Appends rows to <run_dir>/ledger.jsonl. The run id is the directory name."""

    def __init__(self, run_dir: Path, *, scenario: str | None = None) -> None:
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / LEDGER_NAME
        self.run_id = self.run_dir.name
        self.scenario = scenario

    def record(
        self, *, stage: str, model: str, usage: Usage, latency_s: float, pr: str | None = None
    ) -> LedgerRow:
        cost, rates = cost_usd(model, usage)
        row = LedgerRow(
            run_id=self.run_id,
            pr=pr,
            scenario=self.scenario,
            stage=stage,
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            usd_per_mtok=rates,
            cost_usd=cost,
            cost_source="estimated",
            latency_s=round(latency_s, 3),
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        with self.path.open("a") as f:
            f.write(row.model_dump_json() + "\n")
        return row


def read_rows(run_dir: Path) -> list[LedgerRow]:
    path = Path(run_dir) / LEDGER_NAME
    if not path.exists():
        return []
    return [LedgerRow.model_validate_json(line) for line in path.read_text().splitlines() if line]


def rollup(rows: list[LedgerRow]) -> dict:
    """Spend per stage, PR, model and scenario, plus the total and call/token counts.

    The merged-change summary (pr=None) is shown once, and also split evenly across the
    run's PRs to show the per-PR share of the reused summary.
    """
    by: dict[str, dict[str, float]] = {
        k: defaultdict(float) for k in ("stage", "pr", "model", "scenario")
    }
    for r in rows:
        by["stage"][r.stage] += r.cost_usd
        by["pr"][r.pr or "(shared: merged summary)"] += r.cost_usd
        by["model"][r.model] += r.cost_usd
        by["scenario"][r.scenario or "-"] += r.cost_usd
    prs = sorted({r.pr for r in rows if r.pr})
    shared = sum(r.cost_usd for r in rows if r.pr is None)
    return {
        "total_usd": sum(r.cost_usd for r in rows),
        "calls": len(rows),
        "input_tokens": sum(r.input_tokens for r in rows),
        "output_tokens": sum(r.output_tokens for r in rows),
        "by_stage": dict(by["stage"]),
        "by_pr": dict(by["pr"]),
        "by_model": dict(by["model"]),
        "by_scenario": dict(by["scenario"]),
        "merged_summary_usd": shared,
        "merged_summary_per_pr_usd": shared / len(prs) if prs else None,
    }


def format_rollup(summary: dict) -> str:
    lines = [
        (
            f"total: ${summary['total_usd']:.4f}  ({summary['calls']} calls, "
            f"{summary['input_tokens']} in / {summary['output_tokens']} out tokens)"
        )
    ]
    for key in ("by_stage", "by_pr", "by_model", "by_scenario"):
        lines.append(f"{key.removeprefix('by_')}:")
        for name, usd in sorted(summary[key].items()):
            lines.append(f"  {name:<40} ${usd:.4f}")
    per_pr = summary["merged_summary_per_pr_usd"]
    if per_pr is not None:
        lines.append(
            f"merged summary: ${summary['merged_summary_usd']:.4f} once, "
            f"${per_pr:.4f} per PR when shared"
        )
    return "\n".join(lines)
