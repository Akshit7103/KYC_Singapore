"""Lightweight in-memory session authentication for the internal tool.

A single set of credentials (from the environment / .env) gates the whole app.
On a successful login a random token is stored in memory and handed to the
browser as an HTTP-only cookie. Sessions reset whenever the server restarts.

Because sessions live in process memory this supports exactly one instance.
Running multiple replicas would scatter sessions across them and log users out
at random — move to a shared store (Redis, or a sessions table) before scaling.
"""
import secrets

from .config import settings

COOKIE_NAME = "kyc_session"
_sessions: set[str] = set()


def _const_eq(a: str, b: str) -> bool:
    """Constant-time comparison, safe for non-ASCII credentials."""
    return secrets.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def verify_credentials(username: str, password: str) -> bool:
    # Both halves always run so the response time does not reveal which failed.
    user_ok = _const_eq(username, settings.AUTH_USERNAME)
    pass_ok = _const_eq(password, settings.AUTH_PASSWORD)
    return user_ok and pass_ok


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions.add(token)
    return token


def is_valid(token: str | None) -> bool:
    return bool(token) and token in _sessions


def drop_session(token: str | None) -> None:
    _sessions.discard(token)
