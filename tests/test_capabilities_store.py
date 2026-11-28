"""The capabilities cache: each gate's last GateResult, with its age.

The page renders only what this store holds; probing happens on the
explicit re-test POST and lands here. Tests use a controllable clock,
faked adapters and a real temp file for the persistence case: no gate
run here touches the network, OneDrive or a process listing.
"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT / "src"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from probe_fakes import gate as make_gate

from nexuusbot.capabilities import (
    GATES,
    CapabilitiesCache,
    default_gate_runners,
)
from nexuusbot.probe.adapters import Adapters
from nexuusbot.probe.core import (
    FAIL,
    GATE_EMBEDDINGS,
    GATE_KEYS,
    PASS,
    ReachResult,
    RunResult,
)


class FakeClock:
    """The store's clock under test control: nothing ages by accident."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _cache(clock: FakeClock | None = None) -> CapabilitiesCache:
    return CapabilitiesCache(sqlite3.connect(":memory:"), clock or FakeClock())


# -- save, read, stamp -------------------------------------------------------


def test_save_then_get_round_trips_the_gate_result():
    clock = FakeClock()
    cache = _cache(clock)
    result = make_gate(
        "exec-user-space", 1, PASS, evidence=("line one", "line two"), note="hello-world ran"
    )
    cached = cache.save_result(result)

    assert cached.key == "exec-user-space"
    assert cached.updated_ts == clock.now
    assert cached.result == result
    assert cache.cached("exec-user-space") == cached


def test_an_unknown_key_reads_none():
    assert _cache().cached("uv-tls-bootstrap") is None


def test_saving_again_upserts_and_moves_the_timestamp():
    clock = FakeClock()
    cache = _cache(clock)
    cache.save_result(make_gate("exec-user-space", 1, PASS))
    clock.advance(120)
    cache.save_result(make_gate("exec-user-space", 1, FAIL, note="blocked"))

    stored = cache.cached("exec-user-space")
    assert stored.result.status == FAIL
    assert stored.result.note == "blocked"
    assert stored.updated_ts == 1_000_120.0


def test_results_persist_across_a_reopen(tmp_path):
    db = tmp_path / "capabilities.sqlite3"
    clock = FakeClock()
    first = CapabilitiesCache(sqlite3.connect(db), clock)
    first.save_result(make_gate("onedrive-sync", 4, PASS, note="sync root writable"))
    first.conn.close()

    reopened = CapabilitiesCache(sqlite3.connect(db), clock)
    stored = reopened.cached("onedrive-sync")
    assert stored is not None
    assert stored.result.status == PASS
    assert stored.result.note == "sync root writable"
    assert stored.updated_ts == clock.now


def test_evidence_comes_back_as_the_tuple_the_gates_produce():
    # JSON storage turns tuples into lists; the store must hand back the
    # shape the gates (and their tests) work with.
    cache = _cache()
    cache.save_result(make_gate("edr-identity", 5, PASS, evidence=("a", "b")))

    stored = cache.cached("edr-identity")
    assert isinstance(stored.result.evidence, tuple)
    assert stored.result.evidence == ("a", "b")


def test_to_json_is_the_wire_shape_the_api_answers():
    cache = _cache()
    cached = cache.save_result(
        make_gate("power-automate-flows", 3, FAIL, evidence=("GET failed",), note="unreachable")
    )

    payload = cached.to_json()
    assert payload["key"] == "power-automate-flows"
    assert payload["result"]["status"] == "FAIL"
    assert payload["result"]["note"] == "unreachable"
    assert payload["result"]["evidence"] == ["GET failed"]
    assert payload["updatedTs"] == cached.updated_ts


# -- the gate table and the default runner set -------------------------------


def _counted(value, counter: dict):
    """A callable adapter that counts its calls and returns one value."""

    def call(*_args, **_kwargs):
        counter["calls"] += 1
        return value

    return call


def _fake_adapters(counter: dict) -> Adapters:
    return Adapters(
        runner=_counted(RunResult(returncode=0, stdout="PROBE_OK\n"), counter),
        find_uv=_counted(None, counter),
        reach=_counted(ReachResult(url="x", status=200), counter),
        list_processes=_counted(RunResult(returncode=0, stdout=""), counter),
        discover_onedrive=_counted(None, counter),
        write_text=lambda path, text, encoding="utf-8": None,
        copy_file=lambda source, dest: None,
    )


def test_the_gate_table_names_all_the_gates():
    # Five environment gates, then the endpoint embeddings gate (#95):
    # the embeddings probe rides the same cache-then-retest surface but
    # is not part of the CLI environment verdict, so it sits after
    # GATE_KEYS in the table.
    assert [entry[0] for entry in GATES][:5] == list(GATE_KEYS)
    assert [entry[0] for entry in GATES][5] == GATE_EMBEDDINGS
    assert [entry[1] for entry in GATES] == [1, 2, 3, 4, 5, 6]


def test_default_gate_runners_match_what_the_gates_themselves_say(tmp_path):
    # The page titles never-tested cards from this table; it must agree
    # with the gate code, so the two can never drift apart.
    runners = default_gate_runners(tmp_path, _fake_adapters({"calls": 0}))
    by_key = {entry[0]: entry for entry in GATES}
    for key, run in runners.items():
        result = run()
        _key, number, title = by_key[key]
        assert result.key == key
        assert result.number == number
        assert result.title == title


def test_building_the_runner_set_probes_nothing_and_calling_one_gate_runs_one(tmp_path):
    counter = {"calls": 0}
    adapters = _fake_adapters(counter)
    runners = default_gate_runners(tmp_path, adapters)

    # Construction binds closures only: no subprocess, no network.
    assert counter["calls"] == 0

    runners["power-automate-flows"]()
    # One gate ran; the shared runner counter shows nothing else did.
    assert counter["calls"] == 1

    runners["power-automate-flows"]()
    assert counter["calls"] == 2
