"""Path classifiers for risky file categories."""

from pathlib import PurePosixPath

from rebase_agent import config
from rebase_agent.models import CATEGORIES, Category


def categories(path: str) -> set[Category]:
    p = PurePosixPath(path)
    found: set[Category] = set()
    if p.name in config.LOCKFILE_NAMES:
        found.add("lockfile")
    if any(f"/{d}/" in f"/{p.parent}/" for d in config.MIGRATION_DIRS):
        found.add("migration")
    if path.startswith(config.CI_PREFIXES):
        found.add("ci")
    is_root = len(p.parts) == 1
    if "lockfile" not in found and (
        p.name in config.CONFIG_NAMES or (is_root and p.suffix in config.CONFIG_SUFFIXES)
    ):
        found.add("config")
    if config.AUTH_DIR in p.parts[:-1] or (p.suffix == ".py" and "auth" in p.stem):
        found.add("auth")
    return found


def classify(paths: list[str]) -> dict[Category, list[str]]:
    result: dict[Category, list[str]] = {c: [] for c in CATEGORIES}
    for path in sorted(paths):
        for cat in categories(path):
            result[cat].append(path)
    return result
