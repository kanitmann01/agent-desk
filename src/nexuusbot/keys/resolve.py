"""Job resolution (spec 018 #233): one pure function answers which
connection serves a job.

The order is the spec's, one answer per model call: the job's own
binding, the default binding, the single enabled connection, the
environment, and only then an explicit error that says no AI key is
saved. A row that cannot serve a call never wins a leg: the hub steps
over a disabled row and over one whose key was cleared (the row's masked
hint is empty and its provider is not one of the local, key-free
presets), so the lower legs answer instead of a call going out with an
empty key. Saved connections win over the environment, which is the
desk's documented precedence. The model follows the same order on every
leg (spec 022): the job's own model if one is set, then the serving
connection's model, then the environment's. A connection saved before it
could carry a model has none, so it keeps sending the environment's,
exactly as before. The function is pure by construction: it reads
the rows it is handed and the environment triple it is given (defaulting
to the adapter's own), and it never touches the keychain, so an
environment-supplied key stays in memory and a connection's key is the
caller's to fetch. Every model call-site in the server routes through
this resolution inside one hub; no surface resolves an endpoint any
other way.
"""

from dataclasses import dataclass

from nexuusbot.keys.presets import preset_for
from nexuusbot.keys.store import Connection, JobBinding
from nexuusbot.llm import env_config

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

# What each place is called where a person reads it (spec 022: plain
# words, no internal vocabulary). The first is the fallback every place
# without a choice of its own reads.
JOB_LABELS = {
    "default": "Everything else (plugin builder, meeting breakdowns)",
    "assistant": "Assistant",
    "agents": "Agents",
    "presentations": "Presentations",
    "memory": "Memory",
    "insights": "Insights (what the desk writes on cards)",
    "research-web": "Web research",
}

DEFAULT_JOB = "default"


NO_AI_KEY = "No AI key is saved yet. Add one under Settings, Your AI."


class JobUnbound(Exception):
    """No connection or environment serves the named job.

    Carries the job's key for the surfaces that need it; the message is
    the one plain sentence every surface shows. It names no job, no
    binding and no environment variable, because the person reading it
    cannot act on any of those.
    """

    def __init__(self, job: str) -> None:
        """Keep the job and its sentence together."""
        self.job = job
        super().__init__(NO_AI_KEY)


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
    binding whose connection is missing, or whose row cannot serve a
    call, falls through to the next leg rather than pinning the job to a
    row that would send an empty key.
    """
    if env is None:
        env = env_config()
    env_base, env_key, env_model = env
    by_id = {connection.id: connection for connection in connections}

    binding = _binding_for(bindings, job)
    if binding is not None and _can_serve(by_id.get(binding.connection_id)):
        connection = by_id[binding.connection_id]
        return Resolution(job, "job", connection, connection.base_url, "",
                          _model(connection, binding.model_id, env_model))

    if job != DEFAULT_JOB:
        fallback = _binding_for(bindings, DEFAULT_JOB)
        if fallback is not None and _can_serve(by_id.get(fallback.connection_id)):
            connection = by_id[fallback.connection_id]
            return Resolution(job, "default", connection, connection.base_url,
                              "", _model(connection, fallback.model_id, env_model))

    serving = [connection for connection in connections if _can_serve(connection)]
    if len(serving) == 1:
        return Resolution(job, "single", serving[0], serving[0].base_url, "",
                          _model(serving[0], "", env_model))

    if env_base:
        return Resolution(job, "env", None, env_base, env_key, env_model)

    raise JobUnbound(job)


def _can_serve(connection: Connection | None) -> bool:
    """Whether one saved row can answer a call, read from the row alone.

    A disabled row never serves (the migration's keychain-less rows step
    aside this way), and neither does one whose key was cleared: the
    masked hint is the row's own record that a key exists, and the local
    presets are the only providers that serve without one. The keychain
    itself stays the caller's to read, so the hub stays pure.
    """
    if connection is None or not connection.enabled:
        return False
    if connection.masked_key:
        return True
    preset = preset_for(connection.provider)
    return preset is not None and preset.key_optional


def _model(connection: Connection, explicit: str, env_model: str) -> str:
    """The model one call uses: the job's own, else the one saved with
    the connection's key, else the environment."""
    return explicit or connection.model or env_model


def _binding_for(bindings: list[JobBinding], job: str) -> JobBinding | None:
    """One job's binding from the current rows, or None."""
    for binding in bindings:
        if binding.job_key == job:
            return binding
    return None
