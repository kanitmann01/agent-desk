"""The health endpoint's payload.

Health reports what the app is and what each data source's wiring state
is, honestly: the source table is computed live by the caller
(app.live_sources) at request time, so what /health says is what the
watches actually report, and the dashboard's source line reads the same
table.
"""

import time
from collections.abc import Callable

from agentdesk.server.core import SourceStatus

APP_NAME = "agent-desk"


def health_payload(
    version: str,
    sources: list[SourceStatus],
    started_monotonic: float,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Build the /health document. Structure is stable; values move."""
    return {
        "app": APP_NAME,
        "version": version,
        "sources": [
            {"id": s.id, "status": s.status, "detail": s.detail} for s in sources
        ],
        "uptime_seconds": round(max(0.0, clock() - started_monotonic), 1),
    }
