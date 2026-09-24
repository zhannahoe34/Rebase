"""Settings. Path classifiers live here so policy and signals share one list."""

import os
from dataclasses import dataclass

LOCKFILE_NAMES = frozenset(
    {
        "uv.lock",
        "poetry.lock",
        "Pipfile.lock",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "Cargo.lock",
        "go.sum",
        "Gemfile.lock",
    }
)
MIGRATION_DIRS = ("migrations", "alembic/versions")
CI_PREFIXES = (".github/workflows/", ".gitlab-ci.yml", ".circleci/")
CONFIG_SUFFIXES = (".toml", ".yaml", ".yml", ".ini", ".cfg")  # root-level only
CONFIG_NAMES = frozenset({"Dockerfile", "Makefile", ".env", "setup.py"})
AUTH_DIR = "auth"

# --- Phase 2: models, key, prices, policy -------------------------------------------------

API_KEY_ENV = "REBASE_ANTHROPIC_API_KEY"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"

# Defaults only; override per agent with REBASE_MODEL_<AGENT> (PLAN.md §0.2).
DEFAULT_MODELS = {
    "analyst": "claude-haiku-4-5-20251001",
    "orchestrator": "claude-sonnet-5",
    "resolver": "claude-sonnet-5",
    "verifier": "claude-sonnet-5",
}

# Room for adaptive thinking on Sonnet 5 / Opus 5.5 (thinking tokens count toward max_tokens).
MAX_OUTPUT_TOKENS = 16000


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float  # 5-minute cache write
    cache_write_1h: float  # 1-hour cache write (the Agent SDK / Claude Code uses these)


# Source: https://platform.claude.com/docs/en/about-claude/pricing ("Model pricing"),
# fetched 2026-09-24. First-party Claude API, global routing, standard speed.
# A model missing here is an error, never $0 (PLAN.md §0.6).
PRICES_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing (fetched 2026-09-24)"
PRICES: dict[str, Price] = {
    "claude-haiku-4-5-20251001": Price(
        input=1.00, output=5.00, cache_read=0.10, cache_write=1.25, cache_write_1h=2.00
    ),
    "claude-haiku-4-5": Price(
        input=1.00, output=5.00, cache_read=0.10, cache_write=1.25, cache_write_1h=2.00
    ),
    "claude-sonnet-5": Price(
        input=2.00, output=10.00, cache_read=0.20, cache_write=2.50, cache_write_1h=4.00
    ),
    "claude-opus-5-5": Price(
        input=4.00, output=20.00, cache_read=0.20, cache_write=5.00, cache_write_1h=8.00
    ),
}

# Policy (D6). Categories that force escalation; "config" is reported only (Q11).
FORCED_CATEGORIES = ("migration", "lockfile", "ci", "auth")
DEFAULT_CONFIDENCE_FLOOR = 0.7  # Q6 still open: auto_rebase below this becomes escalate.


def model_for(agent: str) -> str:
    return os.environ.get(f"REBASE_MODEL_{agent.upper()}") or DEFAULT_MODELS[agent]


@dataclass(frozen=True)
class Caps:
    """Resolver caps (Q9)."""

    max_turns: int
    max_usd: float


def resolver_caps() -> Caps:
    return Caps(
        max_turns=int(os.environ.get("REBASE_RESOLVER_MAX_TURNS", "20")),
        max_usd=float(os.environ.get("REBASE_RESOLVER_MAX_USD", "1.00")),
    )


def confidence_floor() -> float:
    return float(os.environ.get("REBASE_CONFIDENCE_FLOOR", DEFAULT_CONFIDENCE_FLOOR))


def api_key() -> str:
    key = os.environ.get(API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{API_KEY_ENV} is not set")
    return key
