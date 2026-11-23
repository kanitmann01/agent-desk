"""Job resolution as a pure order table (spec 018 #233, the one unit seam).

The resolver answers one question per model call: which connection serves
this job? The order is the spec's, and these tests walk it leg by leg with
plain data in and a frozen answer out: the job's binding, the default
binding, the single enabled connection, the environment, and the named
"job unbound" error. Saved connections win over the environment; the
function never touches the keychain (env keys stay env keys, connection
keys are fetched by the caller), so the never-write rule holds by
construction.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from agentdesk.keys.resolve import (
    NO_AI_KEY,
    JOBS,
    JOB_LABELS,
    JobUnbound,
    resolve_job,
)
from agentdesk.keys.store import JobBinding, KeysStore
from agentdesk.llm import DEFAULT_MODEL

ENV = ("https://env.example/v1", "env-key", "env-model")


def _connection(tmp_path, label="One", provider="openai",
                base_url="https://a.example/v1", **kwargs):
    """One saved connection in a scratch store, so the dataclass is the
    store's own, never a hand-built lookalike."""
    store = KeysStore(
        __import__("sqlite3").connect(":memory:", check_same_thread=False),
        lambda: 0.0)
    return store.add(label=label, provider=provider, base_url=base_url, **kwargs)


# -- the order table, leg by leg --------------------------------------------


def test_the_jobs_catalog_is_the_spec_seven_with_labels():
    assert JOBS == ("default", "assistant", "agents", "presentations",
                    "memory", "insights", "research-web")
    assert sorted(JOB_LABELS) == sorted(JOBS)
    for job in JOBS:
        assert JOB_LABELS[job]


def test_leg_1_the_jobs_own_binding_wins_over_everything(tmp_path):
    personal = _connection(tmp_path, "Personal", base_url="https://a.example/v1")
    work = _connection(tmp_path, "Work", provider="openai",
                       base_url="https://b.example/v1")
    bindings = [
        JobBinding("default", work.id, "work-model"),
        JobBinding("assistant", personal.id, "assistant-model"),
    ]
    resolved = resolve_job("assistant", connections=[personal, work],
                           bindings=bindings, env=ENV)
    assert resolved.connection is personal
    assert resolved.source == "job"
    assert resolved.base_url == "https://a.example/v1"
    assert resolved.model == "assistant-model"
    assert resolved.api_key == ""  # the key never resolves here; the hub fetches it


def test_leg_1_a_blank_binding_model_falls_back_to_the_env_model(tmp_path):
    conn = _connection(tmp_path)
    resolved = resolve_job(
        "memory", connections=[conn],
        bindings=[JobBinding("memory", conn.id, "")], env=ENV)
    assert resolved.model == "env-model"


def test_leg_2_an_unbound_job_takes_the_default_binding(tmp_path):
    starred = _connection(tmp_path, "Starred", base_url="https://star.example/v1")
    other = _connection(tmp_path, "Other", base_url="https://other.example/v1")
    bindings = [JobBinding("default", starred.id, "default-model")]
    for job in ("presentations", "insights", "research-web"):
        resolved = resolve_job(job, connections=[other, starred],
                               bindings=bindings, env=ENV)
        assert resolved.connection is starred
        assert resolved.source == "default"
        assert resolved.model == "default-model"


def test_leg_2_the_default_job_itself_never_rides_leg_2(tmp_path):
    """The default job resolves through its own binding or falls past it;
    looking itself up in the default binding would be leg 1 twice."""
    starred = _connection(tmp_path, "Starred")
    resolved = resolve_job(
        "default", connections=[starred],
        bindings=[JobBinding("default", starred.id, "m")], env=ENV)
    assert resolved.source == "job"


def test_leg_3_a_single_enabled_connection_serves_every_job(tmp_path):
    only = _connection(tmp_path, "Only")
    for job in JOBS:
        resolved = resolve_job(job, connections=[only], bindings=[], env=ENV)
        assert resolved.connection is only
        assert resolved.source == "single"
        assert resolved.base_url == "https://a.example/v1"
        assert resolved.model == "env-model"


def test_leg_3_never_fires_with_two_connections_or_a_disabled_one(tmp_path):
    one = _connection(tmp_path, "One")
    two = _connection(tmp_path, "Two", base_url="https://b.example/v1")
    assert resolve_job("assistant", connections=[one, two], bindings=[],
                       env=ENV).source == "env"
    import sqlite3

    store = KeysStore(sqlite3.connect(":memory:", check_same_thread=False),
                      lambda: 0.0)
    disabled = store.add(label="Off", provider="openai",
                         base_url="https://a.example/v1")
    store.conn.execute("UPDATE connections SET enabled = 0 WHERE id = ?",
                       (disabled.id,))
    disabled = store.get(disabled.id)
    assert resolve_job("assistant", connections=[disabled], bindings=[],
                       env=ENV).source == "env"


def test_leg_4_the_environment_serves_when_nothing_is_saved(tmp_path):
    resolved = resolve_job("agents", connections=[], bindings=[], env=ENV)
    assert resolved.connection is None
    assert resolved.source == "env"
    assert resolved.base_url == "https://env.example/v1"
    assert resolved.api_key == "env-key"
    assert resolved.model == "env-model"


def test_saved_connections_win_over_the_environment(tmp_path):
    """The documented precedence, asserted in the order itself: with a
    binding (or the single connection) present, the env triple is never
    the answer, even though it carries a base and a key."""
    only = _connection(tmp_path, "Only")
    for job in JOBS:
        resolved = resolve_job(job, connections=[only], bindings=[], env=ENV)
        assert resolved.source == "single"
        assert resolved.api_key == ""


def test_leg_5_nothing_anywhere_is_one_plain_sentence():
    # The error still carries the job for the surfaces that need it. The
    # sentence names the fix and never a job, a binding or an environment
    # variable: the person reading it cannot act on any of those (spec 022).
    for job in JOBS:
        with pytest.raises(JobUnbound) as raised:
            resolve_job(job, connections=[], bindings=[],
                        env=("", "", DEFAULT_MODEL))
        assert raised.value.job == job
        assert str(raised.value) == NO_AI_KEY
        assert "unbound" not in str(raised.value)
        assert "AGENTDESK_" not in str(raised.value)


def test_an_env_base_alone_rescues_every_job_from_unbound():
    # The adapter's env triple always carries a model (its DEFAULT_MODEL),
    # so an env base with the default model is the honest empty-env shape.
    resolved = resolve_job("insights", connections=[], bindings=[],
                           env=("https://only-env.example/v1", "", DEFAULT_MODEL))
    assert resolved.source == "env"
    assert resolved.model == DEFAULT_MODEL


def test_a_binding_whose_connection_is_gone_falls_through(tmp_path):
    """Defensive only (the store's delete cascades the rows): a dangling
    binding must not pin a job to a connection the store no longer has."""
    present = _connection(tmp_path, "Present")
    resolved = resolve_job(
        "assistant", connections=[present],
        bindings=[JobBinding("assistant", "deleted-id", "m")], env=ENV)
    assert resolved.source == "single"
    assert resolved.connection is present


def test_the_default_env_leg_is_the_adapters_own_triple():
    """With no env handed in, the resolver reads the adapter's
    env_config itself, so the hub and the adapter can never disagree
    about what the environment says."""
    from agentdesk.keys import resolve as resolve_module

    captured = {}
    original = resolve_module.env_config

    def spy():
        captured["called"] = True
        return ENV

    resolve_module.env_config = spy
    try:
        resolved = resolve_job("agents", connections=[], bindings=[])
    finally:
        resolve_module.env_config = original
    assert captured.get("called") is True
    assert resolved.source == "env"
