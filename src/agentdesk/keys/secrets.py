"""The keychain half of a connection: secrets through keyring, nothing else.

The database stores a reference and a masked hint; the secret itself
lives in the OS keychain under one service name, one entry per
connection (username ``key/<id>``). The wrapper is thin and injectable
like every store: the server hands it a keyring-shaped backend, tests
hand it MemoryKeychain, and a machine with no viable backend (CI, a
headless box) simply stores no secret - connections still exist, the
settings page says so. No secret is ever written to sqlite, logs or
page HTML from here.
"""

import logging

LOG = logging.getLogger(__name__)

SERVICE = "agent-desk"


def _username(connection_id: str) -> str:
    """The keychain username for one connection: key/<id>, the spec's shape."""
    return f"key/{connection_id}"


class MemoryKeychain:
    """A dict with the keyring module's three methods, for tests.

    Injected through the same constructor seam as the real keyring, so a
    test exercises the wrapper's own code, never a re-implementation of
    it, and no test boot touches a real OS keychain.
    """

    def __init__(self) -> None:
        """Empty vault; the (service, username) pair is the key."""
        self.secrets: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        """The stored secret for the pair, or None when there is none."""
        return self.secrets.get((service, username))

    def set_password(self, service: str, username: str, secret: str) -> None:
        """Store the secret under the pair, replacing any earlier one."""
        self.secrets[(service, username)] = secret

    def delete_password(self, service: str, username: str) -> None:
        """Remove the pair's secret; a missing one is a plain no-op."""
        self.secrets.pop((service, username), None)


class KeychainSecrets:
    """Set, read and drop one connection's key through a keyring backend.

    The backend defaults to the real keyring module (imported lazily so
    merely importing this module costs nothing); an injected backend only
    needs the three password methods, and ``available()`` treats a
    backend without ``get_keyring`` (the injected ones) as always viable.
    """

    def __init__(self, backend=None) -> None:
        """Adopt the backend, building the real keyring client when none."""
        if backend is None:
            import keyring  # the app's second runtime dependency
            backend = keyring
        self._backend = backend

    def available(self) -> bool:
        """True when a usable keychain backend is reachable.

        keyring resolves its active backend at call time; the fail and
        null backends are the library's honest "no keychain here", so
        they are the two that answer False. A backend that cannot even
        be asked is treated the same: the page names the state, the app
        keeps working without stored secrets.
        """
        probe = getattr(self._backend, "get_keyring", None)
        if probe is None:
            return True
        try:
            active = probe()
        except Exception:  # noqa: BLE001 - any discovery failure means no keychain
            LOG.warning("keyring backend discovery failed", exc_info=True)
            return False
        module = type(active).__module__ or ""
        return not module.startswith(("keyring.backends.fail",
                                       "keyring.backends.null"))

    def store(self, connection_id: str, secret: str) -> bool:
        """Put the secret in the keychain; False when it could not land.

        False covers both a missing backend and one that refused, so the
        caller can refuse the save rather than keep a connection whose
        key silently went nowhere.
        """
        if not self.available():
            return False
        try:
            self._backend.set_password(SERVICE, _username(connection_id), secret)
        except Exception:  # noqa: BLE001 - the keychain's refusal is data
            LOG.warning("keychain write failed for %s", connection_id, exc_info=True)
            return False
        return True

    def fetch(self, connection_id: str) -> str | None:
        """The stored secret, or None when there is none to read."""
        if not self.available():
            return None
        try:
            return self._backend.get_password(SERVICE, _username(connection_id))
        except Exception:  # noqa: BLE001 - unreadable is the same as absent
            LOG.warning("keychain read failed for %s", connection_id, exc_info=True)
            return None

    def forget(self, connection_id: str) -> bool:
        """Remove the stored secret; False when there was none to remove.

        The read comes first so the answer says a secret really left the
        keychain, and the delete's own failure is False rather than a
        half-removed state.
        """
        if self.fetch(connection_id) is None:
            return False
        try:
            self._backend.delete_password(SERVICE, _username(connection_id))
        except Exception:  # noqa: BLE001 - a refusal leaves nothing usable anyway
            LOG.warning("keychain delete failed for %s", connection_id, exc_info=True)
            return False
        return self.fetch(connection_id) is None
