"""Settings. Path classifiers live here so policy (Phase 2) and signals share one list."""

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
