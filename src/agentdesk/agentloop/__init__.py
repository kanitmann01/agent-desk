"""The supervised agent loop: the desk's own periodic passes.

One daemon thread wakes on a cadence and runs the registered steps, each
isolated from the others, one pass at a time per data folder. This package
holds the schedule primitives (interval seeding, the run claim) and the
loop itself; the server builds and starts it in create_server and
start_background_polls (spec 016, ticket 04).
"""

from agentdesk.agentloop.loop import AgentLoop, LoopContext, Step, STEPS, register_step
from agentdesk.agentloop.schedule import claim_run, interval_due, release_run

__all__ = [
    "AgentLoop",
    "LoopContext",
    "STEPS",
    "Step",
    "claim_run",
    "interval_due",
    "register_step",
    "release_run",
]
