"""Turn and USD accounting for the resolver (Q9).

The SDK enforces both caps itself (`max_turns`, `max_budget_usd`); we also count turns
from the message stream, map the SDK's cap results to escalation reasons, and turn the
SDK's reported usage into ledger rows (cost_source="sdk_reported").
"""

from typing import Any

from rebase_agent.config import Caps
from rebase_agent.ledger import split_cache_writes
from rebase_agent.models import Usage


class Budget:
    def __init__(self, caps: Caps) -> None:
        self.caps = caps
        self._message_ids: set[str] = set()

    @property
    def turns(self) -> int:
        return len(self._message_ids)

    def observe_assistant(self, message_id: str | None) -> None:
        if message_id:
            self._message_ids.add(message_id)

    def over_turns(self) -> str | None:
        if self.turns > self.caps.max_turns:
            return f"max_turns {self.caps.max_turns} reached"
        return None

    def result_reason(self, subtype: str | None, cost_usd: float | None) -> str | None:
        """Escalation reason for a cap hit reported by the SDK, else None."""
        if subtype == "error_max_turns":
            return f"max_turns {self.caps.max_turns} reached"
        if subtype == "error_max_budget_usd":
            return f"max_usd {self.caps.max_usd:.2f} reached (spent ${cost_usd or 0:.4f})"
        if cost_usd is not None and cost_usd > self.caps.max_usd:
            return f"max_usd {self.caps.max_usd:.2f} exceeded (spent ${cost_usd:.4f})"
        return None


def usage_by_model(
    model_usage: dict[str, Any] | None, run_usage: dict[str, Any] | None = None
) -> dict[str, tuple[Usage, float]]:
    """{model: (tokens, SDK-reported USD)} from ResultMessage.model_usage.

    model_usage doesn't split cache writes by TTL; the run-level usage does. With a single
    model the run-level split applies to it; otherwise writes count as 5-minute.
    """
    models = model_usage or {}
    breakdown = (run_usage or {}).get("cache_creation") if len(models) == 1 else None
    out: dict[str, tuple[Usage, float]] = {}
    for model, u in models.items():
        write_5m, write_1h = split_cache_writes(u.get("cacheCreationInputTokens", 0), breakdown)
        out[model] = (
            Usage(
                input_tokens=u.get("inputTokens", 0),
                output_tokens=u.get("outputTokens", 0),
                cache_read_tokens=u.get("cacheReadInputTokens", 0),
                cache_write_tokens=write_5m,
                cache_write_1h_tokens=write_1h,
            ),
            float(u.get("costUSD", 0.0)),
        )
    return out
