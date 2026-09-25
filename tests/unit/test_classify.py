import pytest

from rebase_agent.signals.classify import categories


@pytest.mark.parametrize(
    "path, expected",
    [
        ("uv.lock", {"lockfile"}),
        ("frontend/package-lock.json", {"lockfile"}),
        ("migrations/0003_x.sql", {"migration"}),
        ("app/alembic/versions/abc.py", {"migration"}),
        (".github/workflows/ci.yml", {"ci"}),
        ("pyproject.toml", {"config"}),
        ("shop/settings.toml", set()),  # config only at the root
        ("Dockerfile", {"config"}),
        ("shop/auth/tokens.py", {"auth"}),
        ("shop/oauth_client.py", {"auth"}),
        ("shop/pricing.py", set()),
        ("docs/migrations.md", set()),
        ("tests/test_auth_expiry.py", {"auth"}),  # a test named after auth counts (Q12)
        ("shop/shipping.py", set()),
        ("shop/tax.py", set()),
        ("docs/CHANGELOG.md", set()),
        ("README.md", set()),
    ],
)
def test_categories(path, expected):
    assert categories(path) == expected
