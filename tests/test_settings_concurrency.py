"""The settings store survives concurrent request threads (#60 stress F1).

The server is a ThreadingHTTPServer and the settings connection is
opened with check_same_thread=False, so the guard's per-request read
(extra_allowed_hosts) races any settings write from another request
thread. Without a lock this intermittently raises InterfaceError /
IndexError on the request hot path and surfaces as a 500. The lock
follows the same pattern the calendar bridge and the research store
already use.
"""

import sqlite3
import threading

from agentdesk.settings import SettingsStore


def _store(tmp_path) -> SettingsStore:
    conn = sqlite3.connect(str(tmp_path / "settings.sqlite3"), check_same_thread=False)
    return SettingsStore(conn)


def test_concurrent_reads_and_writes_never_misuse_the_connection(tmp_path):
    store = _store(tmp_path)
    errors: list[Exception] = []
    start = threading.Barrier(8)
    OPS = 400

    def reader():
        try:
            start.wait()
            for _ in range(OPS):
                store.get("extra_allowed_hosts")
        except Exception as exc:  # noqa: BLE001 - the test collects the misuse
            errors.append(exc)

    def writer(n: int) -> None:
        try:
            start.wait()
            for i in range(OPS):
                store.set("extra_allowed_hosts", f"host{i % 7}:8765" if n else "")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)] + [
        threading.Thread(target=writer, args=(n,)) for n in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"connection misuse under concurrency: {errors[:3]}"
    value = store.get("extra_allowed_hosts")
    assert value == "" or value.startswith("host")
