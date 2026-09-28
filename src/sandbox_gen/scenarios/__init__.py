"""Scenario registry."""

from sandbox_gen.scenarios import (
    auth_touch,
    behavior_change,
    ci_touch,
    conflicting_intent,
    lockfile_touch,
    migration_collision,
    multi_file_conflict,
    real_conflict,
    semantic_break,
    trivial,
    unapproved,
)
from sandbox_gen.scenarios.base import Scenario

SCENARIOS: dict[str, Scenario] = {
    m.SCENARIO.name: m.SCENARIO
    for m in (
        trivial,
        real_conflict,
        semantic_break,
        migration_collision,
        lockfile_touch,
        conflicting_intent,
        behavior_change,
        multi_file_conflict,
        auth_touch,
        ci_touch,
        unapproved,
    )
}

# Push-mode layout: every PR targets main, and scenarios' merged changes land on main in
# waves (one merge commit each). Risky merged changes (migration, lockfile) get their own
# wave, because policy escalates every PR when the merged change touches them.
WAVES: list[tuple[str, list[str]]] = [
    (
        "code",
        [
            "trivial",
            "real_conflict",
            "semantic_break",
            "conflicting_intent",
            "behavior_change",
            "multi_file_conflict",
            "auth_touch",
            "ci_touch",
            "unapproved",
        ],
    ),
    ("risky", ["migration_collision", "lockfile_touch"]),
]
