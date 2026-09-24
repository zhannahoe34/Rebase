"""Scenario registry."""

from sandbox_gen.scenarios import (
    lockfile_touch,
    migration_collision,
    real_conflict,
    semantic_break,
    trivial,
)
from sandbox_gen.scenarios.base import Scenario

SCENARIOS: dict[str, Scenario] = {
    m.SCENARIO.name: m.SCENARIO
    for m in (trivial, real_conflict, semantic_break, migration_collision, lockfile_touch)
}
