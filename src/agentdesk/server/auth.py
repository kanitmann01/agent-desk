"""Session bootstrap: one 256-bit token exchanged for a hardened cookie.

The start command opens the browser at /auth/<token>; exchanging it sets an
HttpOnly, SameSite=Strict session cookie that every later request must
carry (research A9.2 rule 8). The bootstrap token stays valid for the
server's lifetime: losing the cookie is recovered by reopening the auth
URL, the same act as restarting the app, and the URL only ever lives in
localhost browser history. The cookie carries no Secure flag on purpose:
the surface is plain-http loopback by design, and some browsers drop
Secure cookies received over http:// even for 127.0.0.1.
"""

import secrets
import threading
import time
from collections.abc import Callable

from agentdesk.server.core import COOKIE_NAME, SESSION_MAX_AGE

SESSION_LIFETIME_ERROR = "session expired"


def _new_token() -> str:
    """256 bits of entropy, URL-safe by construction."""
    return secrets.token_urlsafe(32)


class SessionStore:
    """Mints and validates sessions behind a mutex.

    The bootstrap token is generated once at startup. Sessions are opaque
    random ids with a wall-clock expiry; the clock is injectable so tests
    can freeze or advance time without sleeping.
    """

    def __init__(
        self,
        max_age: int = SESSION_MAX_AGE,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._max_age = max_age
        self._clock = clock
        self._bootstrap_token = _new_token()
        self._sessions: dict[str, float] = {}
        self._lock = threading.Lock()

    def bootstrap_token(self) -> str:
        return self._bootstrap_token

    def auth_path(self) -> str:
        """The path the start command opens the browser at."""
        return f"/auth/{self._bootstrap_token}"

    def exchange(self, token: str) -> str | None:
        """Exchange the bootstrap token for a fresh session id, or None."""
        if not secrets.compare_digest(token, self._bootstrap_token):
            return None
        sid = _new_token()
        with self._lock:
            self._prune()
            self._sessions[sid] = self._clock() + self._max_age
        return sid

    def validate(self, session_id: str | None) -> bool:
        """True when the cookie value names a live, unexpired session."""
        if not session_id:
            return False
        with self._lock:
            expiry = self._sessions.get(session_id)
            if expiry is None:
                return False
            if self._clock() >= expiry:
                del self._sessions[session_id]
                return False
        return True

    def _prune(self) -> None:
        """Drop expired sessions; caller holds the lock."""
        now = self._clock()
        expired = [sid for sid, exp in self._sessions.items() if now >= exp]
        for sid in expired:
            del self._sessions[sid]

    def cookie_header(self, session_id: str) -> str:
        """The Set-Cookie line for a minted session."""
        return (
            f"{COOKIE_NAME}={session_id}; HttpOnly; SameSite=Strict; "
            f"Path=/; Max-Age={self._max_age}"
        )


def session_id_from_cookie(cookie_header: str | None) -> str | None:
    """Pull the session id out of a request's Cookie header, if any."""
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == COOKIE_NAME and value:
            return value
    return None
