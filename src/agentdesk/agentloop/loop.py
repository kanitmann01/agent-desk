"""Portions adapted from Hermes Agent (github.com/NousResearch/hermes-agent, commit f6c3eb1, cron/scheduler_thread.py and cron/monitor.py), Copyright (c) 2025 Nous Research, MIT License; see licenses/third-party/hermes-agent-LICENSE.txt.

The supervised loop and its step registry. The thread shape is Hermes'
SupervisedTickerThread: one daemon thread ticking on a cadence, a stop
event that closes it promptly, and a supervisor (restart_if_dead) that
respawns a thread that raised out of its target while stop was not asked
for, without ever leaving two alive. The input-hash skip is the monitor
idea (hash_monitor_output) in new code: a step that would call the
endpoint with input it already ran can be skipped by hash.

Each step declares its order (the STEP_ORDER_* constants beside the
registry) and runs isolated: one step raising is an agentloop.step-failed
audit row, and the next step still runs. A pass claims the run slot for
the whole data folder
(schedule.claim_run), writes one agentloop.pass audit row, and remembers
its steps and time for the settings page and the status payload.
"""

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from agentdesk.agentloop import schedule
from agentdesk.assistant import audit as audit_store

LOG = logging.getLogger("agentdesk.agentloop")

# The one interval state latch (an ISO time in the action ledger) and the
# lock file name inside the data folder (spec 016 section 6.2).
LATCH_LAST_RUN = "loop:last_run_at"
LOCK_NAME = "agentloop.lock"

# Spec 016 section 6.2: wake every 60 s, and the first full pass about
# 5 s after boot so the desk acts at once instead of waiting an hour
# (spec 023).
WAKE_SECONDS = 60.0
STARTUP_DELAY = 5.0
DEFAULT_MINUTES = 60


@dataclass(frozen=True)
class Step:
    """One unit of a pass: its name, its declared place, when it applies,
    and what it does.

    order is the step's position in the pass, one of the STEP_ORDER_*
    constants beside the registry: the pass sorts on it (stable on
    registration sequence), so where a step registers and what order the
    modules import in carry no meaning. enabled is read at pass time, so a
    settings flip takes effect without a restart. run receives the
    LoopContext and returns a small dict of counts that becomes the step's
    note in the status payload.
    """

    name: str
    order: int
    enabled: Callable[[Any], bool]
    run: Callable[["LoopContext"], dict]


# The declared pass order (spec 016 section 6.2): a pass heals, then
# recommends, ranks, learns topics, reviews the profile, consolidates
# skills, curates, and only then checks the share, which is the one step
# that can replace the program. The gaps leave later steps room to slot in
# without renumbering. A pass sorts by order, stable on registration
# sequence, so the registration site and the import order stop being
# load-bearing (spec 016 section 6.2).
STEP_ORDER_DESKCHECK = 100
STEP_ORDER_RECOMMEND = 200
STEP_ORDER_RANK = 300
STEP_ORDER_LEARN_TOPICS = 400
STEP_ORDER_PROFILE_REVIEW = 500
STEP_ORDER_SKILLS = 600
STEP_ORDER_CURATOR = 700
STEP_ORDER_UPDATE = 800
# The engine acts last (spec 023): a pass heals, recommends, ranks and
# updates before the engine acts on what all of that found.
STEP_ORDER_ENGINE = 900

# The step registry. Later tickets append their step with register_step
# and a declared order.
STEPS: list[Step] = []


def register_step(step: Step) -> None:
    """Add one step to the registry; its declared order places it in the pass."""
    STEPS.append(step)


def ordered_steps(steps: list[Step] | None = None) -> list[Step]:
    """The steps of one pass in declared order, stable on registration
    sequence for steps that share an order (sorted is stable)."""
    return sorted(STEPS if steps is None else steps,
                  key=lambda step: step.order)


def _input_digest(payload: Any) -> str:
    """The sha256 of a payload's canonical JSON, the no-change fingerprint."""
    encoded = json.dumps(payload, sort_keys=True, default=str,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class LoopContext:
    """Everything one step may read: the live server and the pass's time."""

    server: Any
    ledger: Any
    settings: Any
    now: datetime

    def input_unchanged(self, step: str, payload: Any) -> bool:
        """Whether this step already ran with exactly this input.

        True means the call can be skipped: the stored latch for the step
        holds the same canonical-JSON hash. Without a ledger there is no
        memory, so nothing counts as unchanged.
        """
        if self.ledger is None:
            return False
        return self.ledger.latch_value(f"inputhash:{step}") == _input_digest(payload)

    def remember_input(self, step: str, payload: Any) -> None:
        """Record the input hash after a successful call, so the next
        identical input can be skipped."""
        if self.ledger is None:
            return
        self.ledger.latch(f"inputhash:{step}", _input_digest(payload))


class AgentLoop:
    """The supervised in-process loop, one daemon thread named agent-loop.

    The loop lives and dies with the server process: start() is called from
    start_background_polls, stop() from server_close, and the dashboard's
    GET handler calls restart_if_dead() as the supervisor's heartbeat. The
    cadence and the startup delay are constructor arguments so tests can
    run both in milliseconds.
    """

    def __init__(self, server: Any, *, clock: Callable[[], float] = time.time,
                 wake_seconds: float = WAKE_SECONDS,
                 startup_delay: float = STARTUP_DELAY,
                 data_dir: Path | str | None = None,
                 steps: list[Step] | None = None) -> None:
        """Bind the loop to its server; clock, cadence, data folder and
        steps injectable.

        Nothing opens and nothing writes here: the thread opens in start(),
        the lock file only at claim time, so building a loop is free.
        """
        self.server = server
        self.clock = clock
        self.wake_seconds = wake_seconds
        self.startup_delay = startup_delay
        self._data_dir = data_dir
        # The steps this loop runs; None means the shared registry. A loop
        # that passes its own list runs those, which is how a pass runs
        # with chosen steps without touching the process-wide registry.
        self._steps = None if steps is None else list(steps)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # The manual run-now thread, joined by stop() with the loop thread
        # so neither outlives the stores they write to.
        self._run_thread: threading.Thread | None = None
        # One lock around the shared pass state: the thread, a manual run
        # and the status reader may all touch it at once.
        self._state_lock = threading.Lock()
        self._running = False
        self._last_run_ts: float | None = None
        self._last_steps: list[dict] = []

    # -- collaborators ----------------------------------------------------

    @property
    def lock_path(self) -> Path:
        """The run-claim file, <data>/agentloop.lock for this loop."""
        if self._data_dir is None:
            # Imported at call time: app imports this module, so the reverse
            # import here keeps the dependency acyclic.
            from agentdesk.server.app import default_data_dir

            return default_data_dir() / LOCK_NAME
        return Path(self._data_dir) / LOCK_NAME

    def minutes(self) -> int:
        """The configured interval in minutes; 0 means the loop is off."""
        settings = getattr(self.server, "settings", None)
        if settings is None:
            return DEFAULT_MINUTES
        try:
            return int(settings.get("agent_loop_minutes"))
        except (KeyError, TypeError, ValueError):
            return DEFAULT_MINUTES

    def _now_dt(self) -> datetime:
        """The pass clock as a timezone-aware datetime, from the injectable clock."""
        return datetime.fromtimestamp(self.clock()).astimezone()

    def _latch_epoch(self) -> float | None:
        """The stored last-run time as epoch seconds, or None without one."""
        ledger = getattr(self.server, "ledger", None)
        if ledger is None:
            return None
        stored = ledger.latch_value(LATCH_LAST_RUN)
        if not stored:
            return None
        try:
            return datetime.fromisoformat(stored).timestamp()
        except ValueError:
            return None

    def _audit(self, action: str, target: str = "", detail: str = "",
               status: str = "ok") -> None:
        """Append one row to the audit store when the server has one."""
        conn = getattr(self.server, "audit_conn", None)
        if conn is not None:
            audit_store.record(conn, action, target=target, status=status,
                               detail=detail)

    # -- the pass ----------------------------------------------------------

    def run_pass(self, only: set[str] | None = None) -> list[dict]:
        """Run one pass synchronously: claim, steps, audit, remember.

        only names the steps to run; None runs every enabled step, which
        is what the startup pass and every tick run (spec 023: the first
        pass covers all the steps). A pass that cannot
        claim the run slot records the refusal as its only step row and
        changes nothing else. This is the loop-thread path, so it owns the
        running flag for its duration; when a pass is already running in
        this process (a manual Run now), the call skips outright rather
        than disturb that pass's flag or burn a claim refusal.
        """
        with self._state_lock:
            if self._running:
                return [{"name": "pass", "ok": False, "ms": 0,
                         "note": "Another pass is already running in this process."}]
            self._running = True
        try:
            return self._execute_pass(only)
        finally:
            with self._state_lock:
                self._running = False

    def _execute_pass(self, only: set[str] | None = None) -> list[dict]:
        """Claim and run one pass; the caller owns the running flag.

        Never touches _running itself, which is what keeps the flag's
        single owner true: the loop thread sets and clears it in
        run_pass, a manual run holds its reservation from run_now until
        its job finishes, and neither path can clear the other's.
        """
        started = self.clock()
        if not schedule.claim_run(self.lock_path, now=started):
            refused = [{"name": "claim", "ok": False, "ms": 0,
                        "note": "Another pass holds the run claim."}]
            self._remember(refused, started, ran=False)
            return refused
        try:
            results = self._run_steps(only)
            self._audit("agentloop.pass", detail=", ".join(
                f"{row['name']} {'ok' if row['ok'] else 'failed'}"
                f" in {row['ms']} ms"
                for row in results) or "no steps ran")
            self._remember(results, started, full=only is None)
            return results
        finally:
            schedule.release_run(self.lock_path, start_ts=started)

    def _run_steps(self, only: set[str] | None) -> list[dict]:
        """Run the selected enabled steps in declared order, isolated.

        A step that raises is one failed row and one agentloop.step-failed
        audit row naming it; the steps after it still run.
        """
        settings = getattr(self.server, "settings", None)
        ledger = getattr(self.server, "ledger", None)
        results: list[dict] = []
        for step in ordered_steps(self._steps):
            if only is not None and step.name not in only:
                continue
            try:
                if not step.enabled(settings):
                    continue
            except Exception as exc:  # noqa: BLE001 - a broken gate skips the step
                LOG.exception("agent loop step %s could not be gated", step.name)
                results.append(self._failed_row(step.name, started=time.monotonic(),
                                                exc=exc))
                self._audit("agentloop.step-failed", target=step.name,
                            detail=f"{type(exc).__name__}: {exc}", status="error")
                continue
            started = time.monotonic()
            try:
                context = LoopContext(server=self.server, ledger=ledger,
                                      settings=settings, now=self._now_dt())
                outcome = step.run(context)
                # A step may return its own verdict: an engine turn that
                # failed answers ok False, and the pass must not record it
                # as a success. A dict without ok is a success, as before.
                ok = bool(outcome.get("ok", True)) if isinstance(outcome, dict) else True
                row = {
                    "name": step.name,
                    "ok": ok,
                    "ms": round((time.monotonic() - started) * 1000),
                    "note": _note_text(outcome),
                }
                if isinstance(outcome, dict):
                    # A step's own counts stay readable to the status API
                    # and the readiness walk without being folded into the
                    # note prose: the engine step's backend, action count,
                    # refusal count and verdict live here.
                    row["detail"] = dict(outcome)
                results.append(row)
            except Exception as exc:  # noqa: BLE001 - one step never stops the pass
                LOG.exception("agent loop step %s failed", step.name)
                results.append(self._failed_row(step.name, started, exc))
                self._audit("agentloop.step-failed", target=step.name,
                            detail=f"{type(exc).__name__}: {exc}", status="error")
        return results

    def _failed_row(self, name: str, started: float, exc: BaseException) -> dict:
        """The lastSteps row for one step that could not run."""
        return {
            "name": name,
            "ok": False,
            "ms": round((time.monotonic() - started) * 1000),
            "note": f"{type(exc).__name__}: {exc}",
        }

    def _remember(self, steps: list[dict], started: float, ran: bool = True,
                  full: bool = False) -> None:
        """Keep the pass for the status payload; a full pass also restarts
        the interval clock from its time."""
        with self._state_lock:
            self._last_steps = list(steps)
            if ran:
                self._last_run_ts = started
        if full and ran:
            ledger = getattr(self.server, "ledger", None)
            if ledger is not None:
                ledger.latch(LATCH_LAST_RUN,
                             datetime.fromtimestamp(started).astimezone().isoformat())

    # -- the thread --------------------------------------------------------

    def start(self) -> None:
        """Open the loop's thread; a second call while alive does nothing.

        Guarded by the state lock so two supervisor calls cannot spawn a
        second thread beside the first.
        """
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._spawn_thread_locked()

    def _spawn_thread_locked(self) -> None:
        """Spawn the loop thread and clear the stop request; caller holds
        the state lock, which is what makes the check-then-spawn pair in
        start and restart_if_dead atomic against stop."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="agent-loop",
                                        daemon=True)
        self._thread.start()

    def _run(self) -> None:
        """The thread target: one full startup pass, then the cadence.

        The startup pass runs every step, not just the desk check, so a
        fresh desk acts within seconds of its first start (spec 023) and
        the interval counts from that pass. Nothing here is caught
        wholesale: a bug that raises out of this target kills the thread,
        which is exactly the death the supervisor (restart_if_dead) heals
        on the next dashboard view. Step failures never get that far;
        run_pass isolates each one.
        """
        if self._stop.wait(self.startup_delay):
            return
        if self.minutes() != 0:
            self.run_pass()
        while not self._stop.wait(self.wake_seconds):
            self._tick()

    def _tick(self) -> None:
        """One wake: fire and seed on first sight, run a pass when the
        interval has elapsed."""
        ledger = getattr(self.server, "ledger", None)
        minutes = self.minutes()
        if minutes == 0 or ledger is None:
            return
        now_dt = self._now_dt()
        due, store = schedule.interval_due(
            ledger.latch_value(LATCH_LAST_RUN), minutes / 60, now_dt)
        if store is not None and not due:
            ledger.latch(LATCH_LAST_RUN, store)
        if due:
            self.run_pass()

    def is_running(self) -> bool:
        """Whether a pass holds the run slot right now.

        The public answer the fallback backend reads before it would
        call run_pass(): a pass that is already running must never be
        started again, and its ledger entries must never be re-executed.
        """
        with self._state_lock:
            return self._running

    def stop(self, timeout: float = 2) -> None:
        """Ask both loop threads to stop and join them, bounded by the
        timeout in total, so the stores may close right after.

        The stop request and the thread reads happen under the state lock,
        which closes the window where a supervisor passing its check just
        before shutdown could respawn a thread after this returns.
        """
        with self._state_lock:
            self._stop.set()
            thread = self._thread
            runner = self._run_thread
        deadline = time.monotonic() + timeout
        current = threading.current_thread()
        for worker in (thread, runner):
            if worker is not None and worker is not current:
                worker.join(max(0.0, deadline - time.monotonic()))

    def restart_if_dead(self) -> bool:
        """Respawn the thread if it died while stop was not asked for.

        True when a new thread was started: the supervisor's answer. A loop
        that was stopped on purpose stays down, and a loop that was never
        started is not the supervisor's to open (start_background_polls
        owns the first start). The check and the respawn are one atomic
        step under the state lock, so a stop landing between them cannot
        leave a fresh thread running after shutdown.
        """
        with self._state_lock:
            if self._stop.is_set():
                return False
            thread = self._thread
            if thread is None or thread.is_alive():
                return False
            self._spawn_thread_locked()
            return True

    def run_now(self) -> bool:
        """Start one full pass on a fresh daemon thread, under the same claim.

        False when a pass is already running; the reservation is made
        synchronously, so the answer is exact at return time. The pass
        itself runs through _execute_pass under that reservation (the flag
        has one owner per pass), the thread is tracked so stop() can join
        it before the stores close, and it never starts when stop was
        already asked for.
        """
        with self._state_lock:
            if self._running:
                return False
            self._running = True

            def job() -> None:
                """Run the manual pass and always give the slot back."""
                try:
                    if self._stop.is_set():
                        return
                    self._execute_pass()
                except Exception:  # noqa: BLE001 - the manual path never raises to the caller
                    LOG.exception("manual agent loop pass failed")
                finally:
                    with self._state_lock:
                        self._running = False

            self._run_thread = threading.Thread(target=job, name="agent-loop-run",
                                                daemon=True)
            self._run_thread.start()
        return True

    def status(self) -> dict:
        """The spec 6.2 status payload for /api/agent-loop and the page."""
        minutes = self.minutes()
        with self._state_lock:
            last_ts = self._last_run_ts
            steps = list(self._last_steps)
            running = self._running
        if last_ts is None:
            last_ts = self._latch_epoch()
        next_ts = None
        if minutes != 0:
            base = self._latch_epoch()
            if base is None:
                base = self.clock()
            next_ts = base + minutes * 60
        return {
            "enabled": minutes != 0,
            "intervalMinutes": minutes,
            "lastRunTs": last_ts,
            "nextRunTs": next_ts,
            "running": running,
            "lastSteps": steps,
        }


def _note_text(outcome: Any) -> str:
    """A step's returned counts as the one-line note the tables show."""
    if not outcome:
        return ""
    if isinstance(outcome, str):
        return outcome
    if isinstance(outcome, dict):
        return ", ".join(f"{key} {value}" for key, value in sorted(outcome.items()))
    return str(outcome)


def _deskcheck_enabled(settings: Any) -> bool:
    """The desk check step runs whenever the loop itself runs."""
    return True


def _run_deskcheck(ctx: LoopContext) -> dict:
    """One desk check, healing what it is sure about when autonomy allows."""
    from agentdesk.deskcheck import run_checks
    from agentdesk.ledger import may_act
    from agentdesk.server.app import desk_check_context

    should_fix = ctx.settings is not None and may_act(ctx.settings, "deskcheck.fix")
    result = run_checks(desk_check_context(ctx.server), should_fix=should_fix)
    return {"findings": len(result.findings), "fixed": len(result.fixed),
            "failed": len(result.failed)}


# Ticket 04 registers only the desk check step, which wraps the checks
# (ticket 02) and their fixes (ticket 03). Later tickets append below,
# each with the order its place in the pass declares.
register_step(Step(name="deskcheck", order=STEP_ORDER_DESKCHECK,
                   enabled=_deskcheck_enabled, run=_run_deskcheck))


def _skills_enabled(settings: Any) -> bool:
    """The skills step runs whenever the loop itself runs: consolidate is
    gated by its own create_directly switch, and the feedback drain by
    skills_auto_refine and the endpoint switch, both read at pass time."""
    return True


def _run_skills(ctx: LoopContext) -> dict:
    """Consolidate the asks, then drain the skill feedback queue."""
    from agentdesk.server.app import skills_step_run

    return skills_step_run(ctx)


def _curator_enabled(settings: Any) -> bool:
    """The curator step runs only with the skills_curator switch on."""
    return settings is not None and bool(settings.get("skills_curator"))


def _run_curator(ctx: LoopContext) -> dict:
    """The weekly curation pass, on its own interval."""
    from agentdesk.server.app import curator_step_run

    return curator_step_run(ctx)


# Ticket 10's skills step (consolidation plus refine) and curator step (the
# weekly lifecycle pass) register from server/app.py beside the steps whose
# bodies live there; their declared orders, not the registration site, place
# them after the learned-topics and profile-review steps. The run functions
# above stay here beside the desk check's until a later wave moves the step
# bodies together.
