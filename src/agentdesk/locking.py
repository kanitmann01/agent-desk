"""The one owner of the store-serialization rule and its decorator.

One shared sqlite connection with check_same_thread=False must be
serialized: Python's sqlite3 connection keeps one implicit transaction,
so two threads interleaving on it can commit each other's half-done
writes. The rule's documented origin is the settings store
(agentdesk/settings.py), whose lock fixed the interleaved-cursor
InterfaceError on the guard's hot path. Every store that adopts a shared
connection applies serialized to the methods that touch it and holds one
RLock, re-entrant because locked methods call other locked methods.
"""

import functools
import threading


def store_lock(lock: threading.RLock | None = None) -> threading.RLock:
    """A store's own RLock, or the one handed over by the boot whose
    stores share its connection: one connection, one lock."""
    return lock if lock is not None else threading.RLock()


def serialized(method):
    """Run one store method with the store's re-entrant lock held.

    The whole body runs under self._lock, so two threads never interleave
    on the connection's single transaction; a store that leaves its reads
    unlocked says so itself.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapper
