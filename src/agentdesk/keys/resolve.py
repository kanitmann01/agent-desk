"""Job resolution (spec 018 #233): one pure function answers which
connection serves a job.

The order is the spec's, one answer per model call: the job's own
binding, the default binding, the single enabled connection, the
environment, and only then an explicit "job unbound" error naming the
job. Saved connections win over the environment, which is the desk's
documented precedence. The function is pure by construction: it reads
the rows it is handed and the environment triple it is given (defaulting
to the adapter's own), and it never touches the keychain, so an
environment-supplied key stays in memory and a connection's key is the
caller's to fetch. Every model call-site in the server routes through
this resolution inside one hub; no surface resolves an endpoint any
other way.
"""

from dataclasses import dataclass

from agentdesk.keys.store import Connection, JobBinding
from agentdesk.llm import env_config

# The seven jobs (spec 018): together they cover every model call-site
# the desk makes. default is both a job (the wizard, breakdowns) and the
# fallback binding every unbound job reads.
JOBS = (
    "default",
    "assistant",
    "agents",
    "presentations",
    "memory",
    "insights",
    "research-web",
)

JOB_LABELS = {
    "default": "Default (wizard, meeting breakdowns)",
    "assistant": "Assistant (research bar, chat, paused fills)",
    "agents": "Agents (skills, agent runs)",
    "presentations": "Presentations (plans and fills)",
    "memory": "Memory (extract, retain, reflect, observe, embeddings)",
    "insights": "Insights (readings, plugin suggestions)",
    "research-web": "Web research (presentation research)",
}

DEFAULT_JOB = "default"


class JobUnbound(Exception):
    """No connection or environment serves the named job.

    Carries the job's key; the message is the one sentence every surface
    shows, naming the job and the three ways to bind it.
    """

    def __init__(self, job: str) -> None:
        """Keep the job and its sentence together."""
        self.job = job
        super().__init__(
            f"the {job} job is unbound: bind it to a connection on the"
            " Settings page, star a default connection, or set"
            " AGENTDESK_LLM_BASE")


@dataclass(frozen=True)
class Resolution:
    """One job's answer: the source leg that won, the connection when a
    saved one serves (None on the environment leg), the base URL, the
    key (the environment's own on that leg, always empty on the
    connection legs: the hub fetches it from the keychain), and the
    model."""

    job: str
    source: str  # "job" | "default" | "single" | "env"
    connection: Connection | None
    base_url: str
    api_key: str
    model: str


def resolve_job(job: str, *, connections: list[Connection],
                bindings: list[JobBinding], env: tuple | None = None) -> Resolution:
    """Answer which connection serves one job, in the spec's order.

    connections and bindings are the stores' current rows (empty
    collections when the keys store is absent); env is the
    settings-over-environment triple the adapter resolves (its default,
    the adapter's env_config, keeps the two from ever disagreeing). A
    binding whose connection is missing falls through to the next leg
    rather than pinning the job to a row the store no longer has.
    """
    if env is None:
        env = env_config()
    env_base, env_key, env_model = env
    by_id = {connection.id: connection for connection in connections}

    binding = _binding_for(bindings, job)
    if binding is not None and binding.connection_id in by_id:
        return Resolution(job, "job", by_id[binding.connection_id],
                          by_id[binding.connection_id].base_url, "",
                          binding.model_id or env_model)

    if job != DEFAULT_JOB:
        fallback = _binding_for(bindings, DEFAULT_JOB)
        if fallback is not None and fallback.connection_id in by_id:
            connection = by_id[fallback.connection_id]
            return Resolution(job, "default", connection, connection.base_url,
                              "", fallback.model_id or env_model)

    enabled = [connection for connection in connections if connection.enabled]
    if len(enabled) == 1:
        return Resolution(job, "single", enabled[0], enabled[0].base_url, "",
                          env_model)

    if env_base:
        return Resolution(job, "env", None, env_base, env_key, env_model)

    raise JobUnbound(job)


def _binding_for(bindings: list[JobBinding], job: str) -> JobBinding | None:
    """One job's binding from the current rows, or None."""
    for binding in bindings:
        if binding.job_key == job:
            return binding
    return None
