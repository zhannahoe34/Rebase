"""Session tokens."""

import hashlib


def token_for(user: str, secret: str) -> str:
    """Deterministic session token for a user."""
    return hashlib.sha256(f"{user}:{secret}".encode()).hexdigest()


def check_token(user: str, secret: str, token: str) -> bool:
    return token_for(user, secret) == token
