"""The memory api: the /memory page, its actions and its JSON routes.

Moved verbatim out of server/app.py (spec 017 #217 workstream 11c, the
first of exactly two splits by job): the request gate, routing and the
bootstrap stay in app.py. The mixin's methods answer through self, so
the shared handler machinery they call lives on DashboardHandler; the
memory suites (tests/test_server_memory_*.py) are the proof nothing
changed.
"""

from __future__ import annotations

from dataclasses import replace
import json
import logging
import time

import agentdesk

from agentdesk.assistant import audit as audit_store
from agentdesk.inbox.core import KIND_MEMORY_DRAFT, KIND_MEMORY_REFLECTION
from agentdesk.ledger.store import LedgerError
from agentdesk.memory import loop as memory_loop
from agentdesk.memory.core import UnknownEntity, UnknownFact, normalize_fact_text
from agentdesk.memory.crypto import MemoryEncryptedError
from agentdesk.memory.embed import (
    EmbedderUnavailable,
    EndpointEmbedder,
    effective_embeddings_model,
)
from agentdesk.memory.extract import (
    EndpointExtractor,
    ExtractionFailed,
    ExtractorUnavailable,
    facts_to_retain,
    occurrence_from_source,
)
from agentdesk.memory.reflect import (
    EndpointReflector,
    ReflectEmpty,
    ReflectFailed,
    ReflectorUnavailable,
    accept_observations,
    gather_facts,
    parse_scope_date,
    scope_key,
)
from agentdesk.probe.core import PASS as GATE_PASS
from agentdesk.server.core import SPA_DIR, plain_preview
from agentdesk.server.graph_view import parse_graph_query, render_graph_page
from agentdesk.server.memory_graph_api import build_memory_graph
from agentdesk.server.memory_loop_api import build_loop_state
from agentdesk.server.memory_view import EDIT_MERGE_NOTICE, render_memory_page
from agentdesk.server.research import RETAIN_EXCERPT_MAX_CHARS

LOG = logging.getLogger("agentdesk.server")


def memory_graph_island_built() -> bool:
    """True when the committed SPA build carries the memory graph island
    (a source checkout without a build keeps the static graph link)."""
    return (SPA_DIR / "assets" / "memory-graph.js").is_file()

def memory_loop_island_built() -> bool:
    """True when the committed SPA build carries the Memory page island
    (capture, review, knowledge, removal); without it /memory stays the
    server-rendered page."""
    return (SPA_DIR / "assets" / "memory-loop.js").is_file()

def _scope_text(value) -> str:
    """An optional reflect scope field (ticket #93): anything that is
    not a string, or is blank once trimmed, reads as absent."""
    if not isinstance(value, str):
        return ""
    return value.strip()

def _fact_json(fact) -> dict:
    """A fact as the API answers it."""
    return {
        "id": fact.id,
        "text": fact.text,
        "source": fact.source,
        "createdTs": fact.created_ts,
    }

def _memory_entity_id(value) -> int | None:
    """A body's entity id, or None when it is not one (ticket #92's
    merge form posts ids)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value

class _AuditedEmbedder:
    """The audit wrapper around the embeddings client (ticket #95): one
    ``llm.embeddings`` row per endpoint call, the same fields the
    assistant loop writes for every outbound model call (endpoint,
    model, input size, status), never the text itself. The store calls
    this object exactly like the raw client; injecting a raw client (a
    test does) stays silent by design, the caller's audit, not the
    port's."""

    def __init__(self, inner, base_url: str, audit_conn) -> None:
        """Wrap the client, naming the endpoint its audit rows will carry and the
        connection to write them to.

        An audit_conn of None turns the audit off for this instance and leaves the
        embedding path untouched.
        """
        self._inner = inner
        self._base_url = base_url
        self._audit_conn = audit_conn

    @property
    def model(self) -> str:
        """The wrapped client's model name, passed straight through.

        It is copied onto every audit row, so the log names the model that answered.
        """
        return self._inner.model

    @property
    def last_request_bytes(self) -> int:
        """The byte count of the wrapped client's last call, or 0 when it reports none.

        Read with getattr because the port does not require the attribute.
        """
        return int(getattr(self._inner, "last_request_bytes", 0) or 0)

    def embed(self, text: str):
        """Embed one text, auditing the attempt even when it fails.

        Success writes one row; either failure writes a row with the exception type or
        message cut to 200 characters and then re-raises, so every endpoint call leaves
        exactly one llm.embeddings row.
        """
        request_bytes = len(text.encode("utf-8"))
        try:
            vector = self._inner.embed(text)
        except EmbedderUnavailable as exc:
            self._record("error", request_bytes, str(exc)[:200])
            raise
        except Exception as exc:  # noqa: BLE001 - classified, then raised
            self._record("error", request_bytes, f"{type(exc).__name__}: {exc}"[:200])
            raise
        self._record("ok", request_bytes)
        return vector

    def _record(self, status: str, request_bytes: int, detail: str = "") -> None:
        """Write one llm.embeddings row, or nothing when no audit connection was injected.

        Only sizes and status are recorded; the text being embedded never reaches the
        log.
        """
        if self._audit_conn is None:
            return
        audit_store.record(
            self._audit_conn,
            "llm.embeddings",
            target=self._base_url,
            status=status,
            model=self.model,
            request_bytes=request_bytes,
            detail=detail,
        )


class MemoryApiMixin:
    """The memory surface's handler methods, moved unchanged."""

    # -- memory: the page and its actions (tickets #42, #94) --------------

    def _configure_memory_embeddings(self) -> None:
        """Derive the memory store's semantic half for this action
        (ticket #95): the semantic_memory toggle (default on), the
        embeddings probe's cached answer (a PASS only; the page's
        re-test is what produced it), and a saved endpoint to ask. Any
        miss leaves the store inert, so recall is the deterministic
        hybrid exactly as before this ticket. The embedder is wrapped
        in the audit rows every outbound call owes; the store is a
        long-lived object, so the derived pair is written back onto it
        per action rather than per boot."""
        server = self.server  # type: ignore[attr-defined]
        memory = server.memory
        if memory is None or memory.locked_cause is not None:
            return
        settings = server.settings
        active = True if settings is None else bool(settings.get("semantic_memory"))
        cache = server.capabilities_cache
        cached = cache.cached("embeddings") if cache is not None else None
        passed = cached is not None and cached.result.status == GATE_PASS
        # The embeddings ride the memory job through the hub (spec 018
        # #233): a bound connection serves with its own base and key, and
        # its label is the name the llm.embeddings rows carry; with no
        # connection the settings-over-environment leg keeps answering.
        resolved = self._job_resolution("memory")
        base = key = serving_name = ""
        if resolved is not None:
            if resolved.connection is not None:
                connection = resolved.connection
                base = connection.base_url
                key = server.keychain.fetch(connection.id) or ""
                serving_name = connection.label
                try:
                    server.keys.record_use(connection.id)
                except Exception:  # noqa: BLE001 - the stamp never fails the embeddings
                    LOG.debug("could not stamp last_used_at for %s",
                              connection.id, exc_info=True)
            else:
                base = resolved.base_url
                key = resolved.api_key
                serving_name = resolved.base_url
        embedder = None
        if active and passed and base:
            embedder = _AuditedEmbedder(
                EndpointEmbedder(base, key, effective_embeddings_model(settings)),
                base_url=serving_name or base,
                audit_conn=server.audit_conn,
            )
        memory.embedder = embedder
        memory.embeddings_active = embedder is not None

    def _memory_available(self):
        """The store check every memory route rides: None means the
        response is already sent. A locked store (a marker without its
        key, a wrong key, a key on a populated plaintext bank) refuses
        with its specific plain-language cause, never silently reading
        or writing plaintext."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return None
        if memory.locked_cause is not None:
            self._send_json(503, {"error": memory.locked_cause})
            return None
        return memory

    def _send_memory_page(
        self,
        recall: list | None = None,
        query: str = "",
        encrypt: dict | None = None,
        sweep: list | None = None,
        notice: str | None = None,
    ) -> None:
        """The memory page; with a recall preview when a query came in,
        the encryption state alongside the facts, the entities with
        their merge form (ticket #92), the junk-sweep preview when
        asked, and the locked banner alone when the store is locked."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            page = render_memory_page(
                [], agentdesk.__version__, locked=memory.locked_cause,
                inbox_count=self._inbox_waiting_count(),
            )
        else:
            if encrypt is None:
                encrypt = {"already": True} if memory.is_sealed else {"link": True}
            page = render_memory_page(
                memory.all(), agentdesk.__version__, recall=recall, query=query,
                encrypt=encrypt, entities=memory.entities(), sweep=sweep,
                notice=notice, observations=memory.observations(),
                embeddings=memory.embedding_counts(),
                inbox_count=self._inbox_waiting_count(),
                graph_island=memory_graph_island_built(),
                loop_island=memory_loop_island_built(),
            )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _memory_add(self) -> None:
        """The page's typed-fact path. (The Assistant and Research create
        facts only through capture, which the memory settings govern and
        review gates by default.) Ticket #95: the
        semantic half is derived per action, so an active fact embeds
        at write and a failure stores the fact without a vector."""
        memory = self._memory_available()
        if memory is None:
            return
        self._configure_memory_embeddings()
        body = self._read_json_body() or {}
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            self._send_json(400, {"error": 'expected {"text": "..."}'})
            return
        # Typed facts keep the user's words; the names they mention link
        # them to entities, so supersede and consolidation see them too.
        outcome = memory_loop.store_fact(
            memory, text.strip(), source="page", entities=memory_loop.names_in(text),
        )
        self._schedule_observation_pass()
        self._after_memory_change()
        self._respond_form_or_json("/memory", _fact_json(outcome.fact), 201)

    def _memory_edit(self, fact_id: int | None) -> None:
        """Rewrite one fact's text.

        404 for an id that names no fact and 400 for a body with no text. An edit whose
        new text matches another fact merges into it: a form post re-renders the page
        with the merge notice, while JSON returns the surviving fact with
        mergedIntoExisting set, so neither client has to guess which fact it now holds.
        """
        if fact_id is None:
            self._send_error_page(404, "Nothing here", "No fact lives at this address.")
            return
        memory = self._memory_available()
        if memory is None:
            return
        self._configure_memory_embeddings()
        body = self._read_json_body() or {}
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            self._send_json(400, {"error": 'expected {"text": "..."}'})
            return
        try:
            result = memory.edit(fact_id, text.strip())
        except UnknownFact as exc:
            self._send_json(404, {"error": str(exc)})
            return
        self._after_memory_change()
        # Ticket #92: an edit that landed on another fact's text merged
        # into it; a form post renders the page with the plain notice,
        # JSON carries the flag alongside the surviving fact.
        if result.merged_into and self._is_form_submit():
            self._send_memory_page(notice=EDIT_MERGE_NOTICE)
            return
        payload = _fact_json(result.fact)
        payload["mergedIntoExisting"] = result.merged_into
        self._respond_form_or_json("/memory", payload)

    def _memory_delete(self, fact_id: int | None) -> None:
        """Remove one fact, holding it for undo.

        The plan and the apply both receive the pending source ids, so a removal that
        keeps some sources keeps the same set at both stages. The removal is audited by
        count and followed by an observation pass; the answer names the deleted id.
        """
        if fact_id is None:
            self._send_error_page(404, "Nothing here", "No fact lives at this address.")
            return
        memory = self._memory_available()
        if memory is None:
            return
        try:
            plan = memory_loop.plan_removal(
                memory, "fact", fact_id, keep_source_ids=self._pending_source_ids())
        except memory_loop.UnknownTarget as exc:
            self._send_json(404, {"error": str(exc)})
            return
        memory_loop.apply_removal(memory, plan, keep_source_ids=self._pending_source_ids())
        self._audit("memory.remove", target=f"fact {fact_id}", detail="1 fact")
        self._schedule_observation_pass()
        self._after_memory_change()
        self._respond_form_or_json("/memory", {"deleted": fact_id})

    def _memory_sweep_page(self) -> None:
        """The sweep's dry run (ticket #92): the memory page with the
        candidates, each carrying its reason and a checkbox. A locked
        store renders the banner, like the main page does."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._send_memory_page()
            return
        self._send_memory_page(sweep=memory.sweep_candidates())

    def _memory_graph_page(self) -> None:
        """The memory graph page (ticket #96): the snapshot's static
        SVG in this app's page style. A locked store renders the
        memory page's banner, like the sweep's dry run does; the query
        string parses defensively (memory dates, a clamped limit), so
        the page renders whatever arrives."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._send_memory_page()
            return
        _path, _sep, query = self.path.partition("?")
        since, until, limit = parse_graph_query(query)
        snapshot = memory.graph_snapshot(since=since, until=until, limit=limit)
        page = render_graph_page(
            snapshot,
            agentdesk.__version__,
            since=since,
            until=until,
            inbox_count=self._inbox_waiting_count(),
            island_query=query if memory_graph_island_built() else None,
        )
        self._send_bytes(200, page.encode("utf-8"), "text/html; charset=utf-8")

    def _memory_graph_json(self) -> None:
        """The Memory page graph's data (GET /api/memory/graph): the
        store's real facts, observations, entities, retained excerpts
        and the actions that wrote them, with each node's provenance.
        Same window vocabulary as the static graph page; a locked store
        answers 423 with its cause and reads nothing."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"status": "unavailable",
                                  "error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._send_json(423, {"status": "locked", "error": memory.locked_cause})
            return
        self._configure_memory_embeddings()
        _path, _sep, query = self.path.partition("?")
        since, until, limit = parse_graph_query(query)
        payload = build_memory_graph(
            memory,
            inbox=self.server.inbox,  # type: ignore[attr-defined]
            since=since,
            until=until,
            limit=limit,
            semantic=bool(memory.embeddings_active),
        )
        self._send_json(200, payload)

    # -- the memory loop: capture, the page's state, removal and undo ------

    def _capture_memory(self, channel: str, excerpt: str, own_words: str,
                        use_model: bool = True, candidates=None) -> None:
        """Offer what just flowed through a channel to the memory loop.
        Runs off the request thread (one capture at a time) so a reply is
        never slowed by extraction; any failure is logged, never raised
        into the turn that triggered it. A turn the endpoint just failed
        (`use_model` false) goes straight to the rules instead of asking
        the same endpoint again."""
        server = self.server  # type: ignore[attr-defined]
        memory = server.memory
        if memory is None or memory.locked_cause is not None:
            return
        settings = memory_loop.capture_settings(server.settings)
        if not settings.captures(channel):
            return
        if candidates is not None:
            use_model = False  # the channel wrote its own candidates
        extractor, endpoint, model = self._capture_extractor() if use_model else (None, "", "")
        extract = extractor.extract if extractor is not None else None

        def job() -> None:
            """The capture itself, on the background runner's thread.

            The lock is what keeps captures to one at a time. A failure is logged and
            swallowed, because capture must never break the turn that triggered it. The
            llm.retain row is written only when an extractor ran, so a rules-only
            capture adds no model noise. The observation pass is scheduled after the
            lock is released, so the next pass waits on the lock rather than on this
            job.
            """
            with server.memory_capture_lock:
                try:
                    self._configure_memory_embeddings()
                    outcome = memory_loop.capture(
                        memory, server.inbox,
                        channel=channel, excerpt=excerpt[:RETAIN_EXCERPT_MAX_CHARS],
                        own_words=own_words, settings=settings, extract=extract,
                        stage_card=self._capture_card,
                        speaker="Workbook" if channel == "workbook" else "You",
                        candidates=candidates,
                    )
                except Exception:  # noqa: BLE001 - capture must never break a turn
                    LOG.exception("memory capture on %s failed", channel)
                    return
                if outcome is None:
                    return
                if extractor is not None:
                    self._model_audit(
                        "llm.retain", endpoint or "", model or "", self._port_bytes(extractor),
                        status="ok" if outcome.method == memory_loop.METHOD_MODEL else "error",
                        detail=outcome.cause,
                    )
                server.memory_last_capture = {
                    "channel": channel,
                    "channelLabel": memory_loop.CHANNEL_LABELS.get(channel, channel),
                    "method": outcome.method,
                    "cause": outcome.cause,
                    "found": outcome.found,
                    "skipped": outcome.skipped,
                    "staged": len(outcome.card_ids),
                    "stored": len(outcome.fact_ids),
                    "ts": time.time(),
                }
                if outcome.card_ids or outcome.fact_ids:
                    self._audit(
                        "memory.capture", target=channel,
                        detail=(f"{len(outcome.card_ids)} to review, "
                                f"{len(outcome.fact_ids)} saved, by {outcome.method}"),
                    )
                if settings.auto_approve and outcome.fact_ids:
                    self._record_auto_saved(channel, outcome.fact_ids)
                if outcome.card_ids and server.inbox is not None:
                    self._evaluate_inbox(server.inbox)
            if outcome is not None and outcome.fact_ids:
                self._schedule_observation_pass()

        server.memory_capture_runner(job)

    def _record_auto_saved(self, channel: str, fact_ids: tuple[int, ...]) -> None:
        """One ledger entry per auto-saved fact (spec 016 section 6.5).

        The server layer records; the memory loop stays free of ledger
        imports. The undo of an entry deletes exactly that fact; the
        audit row names the channel and the count, never the fact text.
        A failed record never fails the capture it describes."""
        ledger = getattr(self.server, "ledger", None)  # type: ignore[attr-defined]
        if ledger is None:
            return
        for fact_id in fact_ids:
            try:
                ledger.record(
                    actor="agent-desk",
                    action="memory.auto-saved",
                    subject=f"memory:{fact_id}",
                    why="Saved a captured fact without asking.",
                    undo_kind="memory-fact",
                    before=json.dumps({"id": int(fact_id)}).encode("utf-8"),
                    detail={"factId": int(fact_id), "channel": channel,
                            "saved": len(fact_ids)},
                )
            except LedgerError:
                LOG.exception("the auto-save ledger entry for fact %s failed", fact_id)
        self._audit("memory.auto-saved", target=channel,
                    detail=f"{len(fact_ids)} saved without asking")

    # -- the learned profile (spec 016 sections 6.5 and 7) -----------------

    def _send_learned_profile(self) -> None:
        """The learned profile document, exactly as it is stored."""
        store = getattr(self.server, "learned_profile", None)  # type: ignore[attr-defined]
        if store is None:
            self._send_json(503, {"error": "the learned profile is not available"})
            return
        self._send_json(200, store.document())

    def _learned_profile_remove(self) -> None:
        """Remove one learned topic (`{"topic": ...}`) or line (`{"id": ...}`).

        Removing is the user's own edit, so it is not ask-first, and the
        latch set when the topic was learned stays: it never comes back.
        The removal goes through the one helper shape (capture raw(),
        mutate, record `learned-profile`) so Undo puts the document back
        whole while the latch keeps the topic away."""
        server = self.server  # type: ignore[attr-defined]
        store = getattr(server, "learned_profile", None)
        if store is None:
            self._send_json(503, {"error": "the learned profile is not available"})
            return
        body = self._read_json_body() or {}
        entry_id = body.get("id")
        topic = body.get("topic")
        if isinstance(entry_id, str) and entry_id.strip():
            before = store.raw()
            if not store.remove_entry(entry_id.strip()):
                self._send_json(404, {"error": "That learned line is not in the profile."})
                return
            subject, target = f"learned profile:{entry_id.strip()}", entry_id.strip()
        elif isinstance(topic, str) and topic.strip():
            before = store.raw()
            if not store.remove_topic(topic.strip()):
                self._send_json(404, {"error": "That learned topic is not in the profile."})
                return
            subject, target = f"learned profile:{topic.strip()}", topic.strip()
        else:
            self._send_json(400, {"error": "Name the learned line (id) or topic to remove."})
            return
        entry_id_recorded = None
        ledger = getattr(server, "ledger", None)
        if ledger is not None:
            try:
                recorded = ledger.record(
                    actor="user",
                    action="profile.removed",
                    subject=subject,
                    why=f"You removed the learned topic or line: {target}.",
                    undo_kind="learned-profile",
                    before=before,
                    after=store.raw(),
                    detail={"removed": target},
                )
                entry_id_recorded = recorded.id
            except LedgerError:
                LOG.exception("the learned-profile removal record failed")
        self._respond_form_or_json("/settings#learned",
                                   {"removed": True, "entry": entry_id_recorded})

    def _observation_summarizer(self) -> tuple:
        """(summarizer, endpoint, model) for the per-entity observations,
        or (None, "", "") when endpoint calls are off or none is
        configured: then the rules write them."""
        server = self.server  # type: ignore[attr-defined]
        if not self._source_allowed("endpoint_enabled"):
            return None, "", ""
        llm, endpoint, model = self._effective_llm("memory")
        if server.summarizer is not None:
            return server.summarizer, endpoint or "", model or ""
        if endpoint or not server.llm_defaulted_to_env:
            return memory_loop.EndpointSummarizer(llm), endpoint or "", model or ""
        return None, "", ""

    def _observe_audit(self, summarizer, endpoint: str, model: str, written: int,
                       failure: str) -> None:
        """Record what an observation pass did: llm.observe with the count written.

        The detail always names the written count and appends the first 160 characters
        of the failure when there was one. A failed pass still writes a row, so a pass
        that wrote nothing cannot look like a pass that never ran.
        """
        self._model_audit(
            "llm.observe", endpoint or "", model or "", self._port_bytes(summarizer),
            status="error" if failure else "ok",
            detail=(f"{memory_loop.counted(written, 'observation')} written"
                    + (f"; {failure[:160]}" if failure else "")),
        )

    def _schedule_observation_pass(self) -> None:
        """After memory changes: let the endpoint rewrite the observations
        the rules just wrote (or any built from changed facts), off the
        request thread. Coalesced: one pending pass at a time; a change
        during a pass schedules the next one."""
        server = self.server  # type: ignore[attr-defined]
        memory = server.memory
        if memory is None or memory.locked_cause is not None:
            return
        summarizer, endpoint, model = self._observation_summarizer()
        if summarizer is None or server.memory_observe_pending:
            return
        server.memory_observe_pending = True

        def job() -> None:
            """One coalesced observation pass, on the background runner's thread.

            The pending flag is cleared first, so a change that arrives during the pass
            schedules the next one instead of being lost. A failure is logged and leaves
            the rules' text in place. The audit row is written only when the summarizer
            reports calls, so a pass that needed no endpoint call is not recorded as
            one.
            """
            server.memory_observe_pending = False
            with server.memory_capture_lock:
                try:
                    outcome = memory_loop.reconcile_observations(memory, summarize=summarizer)
                except Exception:  # noqa: BLE001 - a failed pass leaves the rules' text
                    LOG.exception("memory observation pass failed")
                    return
            if getattr(summarizer, "calls", 1):
                self._observe_audit(summarizer, endpoint, model,
                                    outcome.model_written, outcome.model_failure)

        server.memory_capture_runner(job)

    def _capture_card(self, candidate, source_id: int, channel: str, method: str):
        """The review card for one captured candidate: the same memory
        draft card the manual save makes, with the channel and the
        extraction method recorded so the page can say where it came
        from and how."""
        label = memory_loop.CHANNEL_LABELS.get(channel, channel)
        names = ", ".join(name for name, _type in candidate.entities)
        how = ("the company endpoint" if method == memory_loop.METHOD_MODEL
               else "the built-in rules (no endpoint answered)")
        return self.server.inbox.add(  # type: ignore[attr-defined]
            kind=KIND_MEMORY_DRAFT,
            origin=(f"Captured from your {label} activity by {how}. "
                    "Approving saves this fact to memory; rejecting leaves nothing behind."),
            title=f"Fact from {label}" + (f": {names}" if names else ""),
            body=f"Captured from {label}." + (f" Mentions {names}." if names else ""),
            action_label="Save to memory",
            draft=candidate.text,
            meta={"memoryFact": {
                "kind": candidate.kind,
                "occurrence_ts": candidate.occurrence_ts,
                "entities": [[name, entity_type] for name, entity_type in candidate.entities],
                "source_id": source_id,
                "channel": channel,
                "method": method,
            }},
        )

    def _pending_source_ids(self) -> set[int]:
        """Excerpts a waiting review card still points at: a removal
        leaves them in place so approving the card later still links."""
        inbox = self.server.inbox  # type: ignore[attr-defined]
        if inbox is None:
            return set()
        ids: set[int] = set()
        for card in inbox.waiting(include_snoozed=True):
            meta = card.meta.get("memoryFact") if isinstance(card.meta, dict) else None
            if isinstance(meta, dict) and isinstance(meta.get("source_id"), int):
                ids.add(int(meta["source_id"]))
        return ids

    def _capture_extractor(self) -> tuple:
        """(extractor, endpoint, model) capture asks first, or (None, "",
        "") when endpoint calls are off or no endpoint is configured."""
        server = self.server  # type: ignore[attr-defined]
        if not self._source_allowed("endpoint_enabled"):
            return None, "", ""
        llm, endpoint, model = self._effective_llm("memory")
        if server.extractor is not None:
            return server.extractor, endpoint or "", model or ""
        if endpoint or not server.llm_defaulted_to_env:
            return EndpointExtractor(llm), endpoint or "", model or ""
        return None, "", ""

    def _extractor_status(self) -> dict:
        """Which extraction method capture will use, with the reason, for the memory page.

        A disabled endpoint or none saved means the built-in rules, each with its own
        sentence; a configured endpoint means the model, naming it and warning that the
        rules take over when it does not answer.
        """
        if not self._source_allowed("endpoint_enabled"):
            return {"mode": memory_loop.METHOD_RULES,
                    "detail": "Endpoint calls are off in Settings, so capture uses the built-in rules on your own words."}
        extractor, _endpoint, model = self._capture_extractor()
        if extractor is not None:
            return {"mode": memory_loop.METHOD_MODEL,
                    "detail": f"Extracting with {model or 'the default model'}. If the endpoint does not answer, the built-in rules take over."}
        return {"mode": memory_loop.METHOD_RULES,
                "detail": "No endpoint is saved in Settings, so capture uses the built-in rules on your own words."}

    def _memory_loop_json(self) -> None:
        """The memory loop's state as JSON, and a chance to re-offer rule-built
        observations.

        423 when the store is locked, carrying the store's own cause. When any
        observation still carries the rules' mark (the bank predates the endpoint, or a
        pass ran while it was down), one pass is scheduled, at most once a minute while
        the page stays open, so looking at the page is what improves it.
        """
        server = self.server  # type: ignore[attr-defined]
        memory = server.memory
        if memory is None:
            self._send_json(503, {"status": "unavailable", "error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._send_json(423, {"status": "locked", "error": memory.locked_cause})
            return
        # Observations the rules wrote (the endpoint was down, or the bank
        # predates it) are offered to the endpoint again, at most once a
        # minute while the page is open.
        now = time.time()
        if now >= server.memory_observe_after and any(
            method == memory_loop.METHOD_RULES for method, _b in memory.observation_marks().values()
        ):
            server.memory_observe_after = now + 60.0
            self._schedule_observation_pass()
        settings = memory_loop.capture_settings(server.settings)
        self._send_json(200, build_loop_state(
            memory, server.inbox, settings.to_json(), self._extractor_status(),
            server.memory_last_capture, server.memory_undo.window_s,
        ))

    def _memory_target(self, body: dict) -> tuple[str, int] | None:
        """The (kind, id) a request names, or None when it names neither properly.

        The id must be a true int: a bool is refused even though Python would accept it
        as one, because a JSON true is not an id. A body without a target field falls
        back to the body itself, so a flat request means what a nested one means.
        """
        target = body.get("target") if isinstance(body.get("target"), dict) else body
        kind = target.get("type")
        raw = target.get("id")
        if kind not in memory_loop.TARGET_TYPES or isinstance(raw, bool) or not isinstance(raw, int):
            return None
        return kind, raw

    def _memory_remove(self, preview: bool) -> None:
        """Preview names everything a removal changes and writes nothing;
        the removal itself writes once, holds an undo for the window and
        records an audit row with counts, never memory text."""
        server = self.server  # type: ignore[attr-defined]
        memory = self._memory_available()
        if memory is None:
            return
        body = self._read_json_body() or {}
        target = self._memory_target(body)
        if target is None:
            self._send_json(400, {"error": 'expected {"target": {"type": "fact|source|entity|observation", "id": <id>}}'})
            return
        kind, target_id = target
        if kind == "source" and not preview and server.inbox is not None:
            # Removing an excerpt also rejects the cards still waiting on it.
            for card in server.inbox.waiting(include_snoozed=True):
                meta = card.meta.get("memoryFact") if isinstance(card.meta, dict) else None
                if isinstance(meta, dict) and meta.get("source_id") == target_id:
                    server.inbox.dismiss(card.id)
        keep = self._pending_source_ids()
        # The preview asks the endpoint for the observations' new text (so
        # the dialog shows what they will read); the removal reuses it.
        summarizer, endpoint, model = self._observation_summarizer() if preview else (None, "", "")
        try:
            plan = memory_loop.plan_removal(
                memory, kind, target_id, keep_source_ids=keep,
                summarize=summarizer,
            )
        except (memory_loop.UnknownTarget, UnknownEntity, UnknownFact) as exc:
            self._send_json(404, {"error": str(exc)})
            return
        if summarizer is not None and getattr(summarizer, "calls", 0):
            self._observe_audit(summarizer, endpoint, model, sum(
                1 for _scope, summary in plan.after.values()
                if summary.method == memory_loop.METHOD_MODEL
            ), "")
        if preview:
            server.memory_previews.put(plan)
            self._send_json(200, {"status": "ok", "plan": plan.to_json(memory)})
            return
        self._configure_memory_embeddings()
        planned = server.memory_previews.take(kind, target_id)
        result = memory_loop.apply_removal(memory, plan, keep_source_ids=keep, planned=planned)
        self._schedule_observation_pass()
        token, expires = server.memory_undo.hold(result, plan.label)
        counts = (f"{memory_loop.counted(len(result.fact_ids), 'fact')}; observations:"
                  f" {len(result.observations_removed)} removed, {len(result.observations_updated)} rewritten,"
                  f" {len(result.observations_flagged)} flagged;"
                  f" {memory_loop.counted(len(result.entities_removed), 'entity', 'entities')} forgotten")
        self._audit("memory.remove", target=f"{kind} {target_id}", detail=counts)
        self._after_memory_change()
        self._send_json(200, {
            "status": "ok",
            "removed": result.to_json(),
            "undo": {"token": token, "expiresTs": expires, "windowS": server.memory_undo.window_s},
        })

    def _memory_undo(self) -> None:
        """Undo a removal inside its window.

        The token is taken out of the buffer, so a second undo with the same token finds
        nothing and answers 410 with the window message. A ValueError means the data
        moved on since the preview and answers 409. A successful undo is audited and
        followed by an observation pass.
        """
        server = self.server  # type: ignore[attr-defined]
        memory = self._memory_available()
        if memory is None:
            return
        body = self._read_json_body() or {}
        token = body.get("token")
        held = server.memory_undo.take(token) if isinstance(token, str) else None
        if held is None:
            self._send_json(410, {"error": "The undo window has passed, so that removal is final."})
            return
        try:
            memory_loop.undo_removal(memory, held)
        except ValueError as exc:
            self._send_json(409, {"error": str(exc)})
            return
        self._schedule_observation_pass()
        self._audit("memory.undo", target=memory_loop.counted(len(held.result.fact_ids), "fact"),
                    detail="removal undone within the window")
        self._after_memory_change()
        self._send_json(200, {"status": "ok", "restored": held.result.to_json()})

    def _memory_keep(self, raw_id: str) -> None:
        """Keep both: a replaced fact rides recall again."""
        memory = self._memory_available()
        if memory is None:
            return
        if not raw_id.isdigit():
            self._send_json(404, {"error": "no fact at this address"})
            return
        try:
            memory.clear_superseded(int(raw_id))
        except UnknownFact as exc:
            self._send_json(404, {"error": str(exc)})
            return
        memory_loop.reconcile_observations(memory)
        self._schedule_observation_pass()
        self._audit("memory.keep", target=f"fact {raw_id}", detail="kept beside its replacement")
        self._send_json(200, {"status": "ok", "kept": int(raw_id)})

    def _memory_sweep(self) -> None:
        """Delete the checked candidates through the donor's removeFacts
        semantics (ticket #92): every id must be a current junk
        candidate and must exist, or the whole call is refused before
        anything is written. The audit row names counts, never fact
        text."""
        memory = self._memory_available()
        if memory is None:
            return
        body = self._read_json_body() or {}
        ids = self._sweep_ids_from_body(body)
        if not ids:
            self._memory_hygiene_error_response(
                400, 'expected {"ids": [...]} or the preview checkboxes'
            )
            return
        candidates = {c.fact.id: c.reason for c in memory.sweep_candidates()}
        for fact_id in ids:
            if fact_id in candidates:
                continue
            try:
                memory.get(fact_id)
            except UnknownFact:
                self._memory_hygiene_error_response(404, f"no fact {fact_id}")
                return
            self._memory_hygiene_error_response(
                400,
                "That fact is not a junk candidate; delete it from the "
                "fact list instead.",
            )
            return
        try:
            removed = memory.remove_facts(ids)
        except UnknownFact as exc:
            # A candidate vanished between the preview and this post.
            self._memory_hygiene_error_response(404, str(exc))
            return
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            audit_store.record(
                self.server.audit_conn, "memory.sweep",
                target=f"{len(removed.fact_ids)} facts",
                detail=(f"swept {len(removed.observation_ids)} orphaned"
                        f" observations and {len(removed.entity_ids)} orphaned"
                        " entities"),
            )
        self._respond_form_or_json("/memory", {
            "status": "ok",
            "deleted": len(removed.fact_ids),
            "removedFactIds": list(removed.fact_ids),
            "removedObservationIds": list(removed.observation_ids),
            "removedEntityIds": list(removed.entity_ids),
        })

    def _sweep_ids_from_body(self, body: dict) -> list[int]:
        """The checked candidate ids: a JSON id list, or one checkbox
        per candidate (the no-JS form's unique names). Anything that is
        not a fact id is a refused call, never a partial delete."""
        raw = body.get("ids")
        if isinstance(raw, list):
            ids: list[int] = []
            for value in raw:
                if isinstance(value, bool) or not isinstance(value, int):
                    return []
                ids.append(value)
            return sorted(set(ids))
        checked: set[int] = set()
        for name, value in body.items():
            if not name.startswith("sweep_") or not value:
                continue
            suffix = name[len("sweep_"):]
            if not suffix.isdigit():
                return []
            checked.add(int(suffix))
        return sorted(checked)

    def _memory_entities_merge(self) -> None:
        """The page's entity merge (ticket #92): union the aliases,
        relink every fact, one entity remains. The audit row names ids,
        never entity names."""
        memory = self._memory_available()
        if memory is None:
            return
        body = self._read_json_body() or {}
        survivor = _memory_entity_id(body.get("survivor"))
        removed = _memory_entity_id(body.get("removed"))
        if survivor is None or removed is None:
            self._memory_hygiene_error_response(
                400, 'expected {"survivor": <id>, "removed": <id>}'
            )
            return
        try:
            merged = memory.merge_entities(survivor, removed)
        except ValueError as exc:
            self._memory_hygiene_error_response(400, str(exc))
            return
        except UnknownEntity as exc:
            self._memory_hygiene_error_response(404, str(exc))
            return
        # The merge deleted both sides' observations inside its
        # transaction; this is the rebuild line every other write runs.
        memory_loop.reconcile_observations(memory)
        self._schedule_observation_pass()
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            audit_store.record(
                self.server.audit_conn, "memory.merge",
                target=str(survivor),
                detail=f"merged entity {removed} into entity {survivor}",
            )
        self._respond_form_or_json("/memory", {
            "status": "ok",
            "survivor": merged.id,
            "survivorName": merged.canonical_name,
            "aliases": list(merged.aliases),
            "type": merged.type,
            "merged": removed,
        })

    def _memory_hygiene_error_response(self, status: int, cause: str) -> None:
        """A refused hygiene action: the error page for a form post, the
        JSON cause for an API call."""
        if self._is_form_submit():
            self._send_error_page(status, "Memory hygiene", cause)
            return
        self._send_json(status, {"error": cause})

    def _memory_recall(self) -> None:
        """The preview: render the page with the ranked answers, best
        first, so the manager sees exactly what the assistant would
        ride. Ticket #95: the query embeds once when the semantic half
        is active; a failure simply leaves the deterministic legs."""
        memory = self._memory_available()
        if memory is None:
            return
        self._configure_memory_embeddings()
        body = self._read_json_body() or {}
        query = body.get("query")
        if not isinstance(query, str) or not query.strip():
            self._send_json(400, {"error": 'expected {"query": "..."}'})
            return
        query = query.strip()
        self._send_memory_page(recall=memory.recall(query), query=query)

    def _memory_encrypt_page(self) -> None:
        """The dry run: the memory page with the conversion form and the
        per-table counts of what would be sealed. An already-encrypted
        bank says so; a locked one renders the banner."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._send_memory_page()
            return
        if memory.is_sealed:
            self._send_memory_page(encrypt={"already": True})
            return
        self._send_memory_page(encrypt={"counts": memory.plain_field_counts()})

    def _memory_encrypt(self) -> None:
        """The one-action conversion, confirm-gated (ticket #94).

        The checkbox is the settings confirmation the spec asks for: no
        confirm field, no conversion. The key file is ensured before the
        transaction, the conversion is one transaction, and the audit
        row names the field count, never a key byte or a fact text."""
        memory = self.server.memory  # type: ignore[attr-defined]
        if memory is None:
            self._send_json(503, {"error": "the memory store is not available"})
            return
        if memory.locked_cause is not None:
            self._memory_error_response(503, memory.locked_cause)
            return
        if memory.is_sealed:
            self._memory_error_response(
                409, "The memory database is already encrypted."
            )
            return
        body = self._read_json_body() or {}
        if not body.get("confirm"):
            self._memory_error_response(
                400,
                "Tick the confirm checkbox: the conversion rewrites every "
                "stored text and cannot be undone without the key.",
            )
            return
        if memory.key_path is None:
            self._memory_error_response(
                503, "No key file location is configured for this memory store."
            )
            return
        try:
            result = memory.encrypt_all()
        except MemoryEncryptedError as exc:
            self._memory_error_response(409, str(exc))
            return
        except (OSError, ValueError) as exc:
            self._memory_error_response(
                503, f"The key file could not be written or read: {exc}"
            )
            return
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            audit_store.record(
                self.server.audit_conn, "memory.encrypt",
                target=f"{result['fields']} fields",
                detail=("memory.sqlite3 encrypted at rest; the key stays"
                        " in memory.key"),
            )
        self._respond_form_or_json("/memory", {"status": "ok", "fields": result["fields"]})

    def _memory_error_response(self, status: int, cause: str) -> None:
        """A refused memory action: the error page for a form post, the
        JSON cause for an API call."""
        if self._is_form_submit():
            self._send_error_page(status, "Memory encryption", cause)
            return
        self._send_json(status, {"error": cause})

    # -- embeddings backfill (ticket #95) ----------------------------------

    def _memory_embeddings_backfill(self) -> None:
        """The memory page's backfill action (ticket #95, the donor's
        backfillEmbeddings): every fact missing a vector embeds
        oldest-first, one committed UPDATE per row, so a mid-run
        failure leaves the prior rows embedded and a retry finishes
        the job. The answer carries the counts either way (embedded N,
        remaining M) and, when the run stopped early, the endpoint's
        plain-language cause. The action's audit row names the counts,
        never a fact text; the individual endpoint calls ride the
        llm.embeddings rows the audited embedder writes."""
        server = self.server  # type: ignore[attr-defined]
        memory = self._memory_available()
        if memory is None:
            return
        self._configure_memory_embeddings()
        if not (memory.embeddings_active and memory.embedder is not None):
            self._memory_embeddings_error_response(
                409,
                "Semantic memory is not active: pass the embeddings probe"
                " on the capabilities page, keep semantic memory on in"
                " settings, and save an endpoint first.",
            )
            return
        try:
            result = memory.backfill_embeddings()
        except MemoryEncryptedError as exc:
            self._memory_embeddings_error_response(503, str(exc))
            return
        counts = f"{result['embedded']} embedded, {result['remaining']} remaining"
        cause = result.get("cause")
        if server.audit_conn is not None:
            audit_store.record(
                server.audit_conn, "memory.embeddings",
                target=counts,
                status="ok" if cause is None else "error",
                detail=cause or "",
            )
        notice = f"Embeddings backfill: {counts}."
        if cause is not None:
            notice = f"Embeddings backfill stopped early: {cause} Counts: {counts}"
            if self._is_form_submit():
                self._send_memory_page(notice=notice)
                return
            self._send_json(200, {
                "status": "error",
                "embedded": result["embedded"],
                "remaining": result["remaining"],
                "cause": cause,
            })
            return
        if self._is_form_submit():
            self._send_memory_page(notice=notice)
            return
        self._send_json(200, {
            "status": "ok",
            "embedded": result["embedded"],
            "remaining": result["remaining"],
            "cause": None,
        })

    def _memory_embeddings_error_response(self, status: int, cause: str) -> None:
        """A refused embeddings action: the error page for a form post,
        the JSON cause for an API call."""
        if self._is_form_submit():
            self._send_error_page(status, "Embeddings", cause)
            return
        self._send_json(status, {"error": cause})

    # -- retain: the chat surface's save-to-memory action (ticket #91) ----

    def _memory_retain(self) -> None:
        """Turn a conversation excerpt into inbox cards, one per
        surviving candidate fact, all sharing one source id.

        The donor writes extracted facts directly; here nothing is
        written until a card is accepted (spec decision 9), and both
        extractor failure classes leave the bank untouched with a
        plain-language error: JSON answers degraded like every LLM
        turn, a form post gets the error page. The endpoint gate and
        the llm.retain audit match every other model call. With no
        extractor injected at construction, an EndpointExtractor is
        built from the effective llm client per call.
        """
        server = self.server  # type: ignore[attr-defined]
        memory = self._memory_available()
        if memory is None:
            return
        if server.inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        body = self._read_json_body() or {}
        excerpt = body.get("excerpt")
        if not isinstance(excerpt, str) or not excerpt.strip():
            self._send_json(400, {"error": 'expected {"excerpt": "..."}: the conversation you want to save'})
            return
        excerpt = excerpt.strip()[:RETAIN_EXCERPT_MAX_CHARS]
        if not self._source_allowed("endpoint_enabled"):
            self._retain_error_response(
                409,
                "Company endpoint calls are turned off in settings, so "
                "this surface is paused. Everything else keeps working.",
            )
            return
        _llm, endpoint, model = self._effective_llm("memory")
        extractor = server.extractor
        if extractor is None:
            extractor = EndpointExtractor(_llm)
        try:
            candidates = extractor.extract(excerpt)
        except (ExtractorUnavailable, ExtractionFailed) as exc:
            self._model_audit("llm.retain", endpoint, model,
                              self._port_bytes(extractor),
                              status="error", detail=str(exc)[:200])
            self._retain_error_response(502, str(exc))
            return
        self._model_audit("llm.retain", endpoint, model,
                          self._port_bytes(extractor))
        kept = [
            replace(candidate, occurrence_ts=occurrence_from_source(excerpt, candidate.occurrence_ts))
            for candidate in facts_to_retain(candidates)
        ]
        if not kept:
            # Nothing survived the donor's filters: no source row, no
            # cards, no writes at all.
            self._respond_form_or_json("/inbox", {"status": "ok", "cards": [], "sourceId": None})
            return
        source_id = memory.add_source(excerpt)
        cards = [self._memory_draft_card(candidate, source_id) for candidate in kept]
        self._evaluate_inbox(server.inbox)
        self._respond_form_or_json("/inbox", {
            "status": "ok",
            "cards": [card.to_json(server.inbox.now_ts()) for card in cards],
            "sourceId": source_id,
        })

    def _port_bytes(self, port) -> int:
        """The bytes of the prompt that went out, when the port can say
        (the built-in ones record it; an injected one may not)."""
        return int(getattr(port, "last_request_bytes", 0) or 0)

    def _model_audit(self, action: str, endpoint: str, model: str,
                     request_bytes: int, status: str = "ok",
                     detail: str = "") -> None:
        """A model call's audit row (llm.retain, llm.reflect), the _ask
        pattern's fields."""
        if self.server.audit_conn is not None:  # type: ignore[attr-defined]
            audit_store.record(
                self.server.audit_conn, action, target=endpoint,
                status=status, model=model, request_bytes=request_bytes, detail=detail,
            )

    def _memory_draft_card(self, candidate, source_id: int):
        """One approval card per candidate: the editable draft is the
        fact text, the meta carries what acceptance writes."""
        names = ", ".join(name for name, _type in candidate.entities)
        mentioned = names if names else "nothing named"
        kind_word = "Experience" if candidate.kind == "experience" else "World"
        return self.server.inbox.add(  # type: ignore[attr-defined]
            kind=KIND_MEMORY_DRAFT,
            origin=("Extracted from a conversation you chose to save. "
                    "Accepting writes this fact to memory; dismissing "
                    "leaves nothing behind."),
            title=f"{kind_word} fact: {mentioned}",
            body=f"From the conversation you saved. Mentions {mentioned}.",
            action_label="Save to memory",
            draft=candidate.text,
            meta={"memoryFact": {
                "kind": candidate.kind,
                "occurrence_ts": candidate.occurrence_ts,
                "entities": [[name, entity_type] for name, entity_type in candidate.entities],
                "source_id": source_id,
            }},
        )

    def _retain_error_response(self, status: int, cause: str) -> None:
        """A failed retain says so in plain language and writes nothing:
        the error page for a form post, the degraded turn shape for JSON."""
        if self._is_form_submit():
            self._send_error_page(status, "Save to memory", cause)
            return
        self._send_json(200, {"status": "degraded", "cause": cause})

    # -- reflect: the memory page's derive-observations action (ticket #93)

    def _memory_reflect(self) -> None:
        """Gather the bank's facts, ask the reflector for observations,
        and stage one approval card per survivor. Nothing lands in the
        memory bank here (spec decision 24): acceptance writes the
        observation, with its citations, through the card's meta. The
        donor writes its accepted observations directly; here both
        reflector failure classes and every filtered-out draft leave
        the bank untouched with a plain-language notice, and the
        endpoint gate and the llm.reflect audit match every other
        model call. With no reflector injected at construction, an
        EndpointReflector is built from the effective llm client per
        call, exactly like the retain route's extractor. Ticket #95:
        when the semantic half is active, every draft also embeds (one
        audited call each, failures degrade) so the near-duplicate
        rule's cosine leg can join.
        """
        server = self.server  # type: ignore[attr-defined]
        memory = self._memory_available()
        if memory is None:
            return
        self._configure_memory_embeddings()
        if server.inbox is None:
            self._send_json(503, {"error": "the inbox is not available"})
            return
        body = self._read_json_body() or {}
        topic = _scope_text(body.get("topic"))
        entity = _scope_text(body.get("entity"))
        try:
            since = parse_scope_date(body.get("since"))
            until = parse_scope_date(body.get("until"))
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return
        if not self._source_allowed("endpoint_enabled"):
            self._reflect_error_response(
                409,
                "Company endpoint calls are turned off in settings, so "
                "this surface is paused. Everything else keeps working.",
            )
            return
        query = " ".join(part for part in (topic, entity) if part)
        try:
            gathered = gather_facts(
                query, memory.recall(query), memory.all(),
                since=since, until=until,
            )
        except ReflectEmpty as exc:
            # Refused before any model call, so nothing to audit.
            self._reflect_error_response(502, str(exc))
            return
        _llm, endpoint, model = self._effective_llm("memory")
        reflector = server.reflector
        if reflector is None:
            reflector = EndpointReflector(_llm)
        try:
            drafts = reflector.reflect(topic or entity, gathered)
        except (ReflectFailed, ReflectorUnavailable) as exc:
            self._model_audit(
                "llm.reflect", endpoint, model, self._port_bytes(reflector),
                status="error", detail=str(exc)[:200],
            )
            self._reflect_error_response(502, str(exc))
            return
        self._model_audit(
            "llm.reflect", endpoint, model, self._port_bytes(reflector)
        )
        try:
            survivors = accept_observations(
                list(drafts), {fact.id for fact in gathered},
                single_entity=bool(entity), vectors=self._draft_vectors(memory, drafts),
            )
        except ReflectFailed as exc:
            # The call itself succeeded and is already audited; the
            # model's answers just did not survive the donor's filters.
            self._reflect_error_response(502, str(exc))
            return
        scope = scope_key(entity=entity, topic=topic, since=since, until=until)
        gathered_by_id = {fact.id: fact for fact in gathered}
        subject = topic or entity
        title = f"Observation: {subject}" if subject else "Observation"
        cards = [
            self._reflection_card(draft, title, scope, gathered_by_id)
            for draft in survivors
        ]
        self._evaluate_inbox(server.inbox)
        self._respond_form_or_json("/inbox", {
            "status": "ok",
            "cards": [card.to_json(server.inbox.now_ts()) for card in cards],
            "rejected": len(drafts) - len(survivors),
        })

    def _draft_vectors(self, memory, drafts) -> dict[str, list[float]]:
        """Each reflector draft's embedding, keyed by its normalized
        text (ticket #95, the donor's reflect: every draft embeds
        through the bank's one embedder, so the map is same-model by
        construction). A failed embed leaves that draft out, which the
        near-duplicate cosine leg reads as no vector, never an error.
        The calls ride the audited wrapper like every other endpoint
        call."""
        vectors: dict[str, list[float]] = {}
        if not (memory.embeddings_active and memory.embedder is not None):
            return vectors
        for draft in drafts:
            key = normalize_fact_text(draft.text)
            if not key or key in vectors:
                continue
            try:
                vectors[key] = list(memory.embedder.embed(draft.text))
            except Exception:  # noqa: BLE001 - the donor's vectorFor
                continue
        return vectors

    def _reflection_card(self, draft, title: str, scope: str,
                         gathered_by_id: dict):
        """One approval card per surviving observation: the editable
        draft is the observation text, the body names the cited facts,
        and the meta carries what acceptance writes (the scope the run
        ran in, the confidence to store, the citations)."""
        cited = [
            fact for fact in
            (gathered_by_id.get(fact_id) for fact_id in draft.fact_ids)
            if fact is not None
        ]
        listing = " | ".join(plain_preview(fact.text) for fact in cited)
        return self.server.inbox.add(  # type: ignore[attr-defined]
            kind=KIND_MEMORY_REFLECTION,
            origin=("Derived from the facts on your memory page. "
                    "Accepting writes this observation with its "
                    "citations; dismissing leaves nothing behind."),
            title=title,
            body=f"Derived from {len(cited)} gathered facts: {listing}",
            action_label="Save observation",
            draft=draft.text,
            meta={"memoryObservation": {
                "scope_key": scope,
                "confidence": draft.confidence,
                "source_fact_ids": list(draft.fact_ids),
            }},
        )

    def _reflect_error_response(self, status: int, cause: str) -> None:
        """A failed reflect says so in plain language and writes
        nothing: the error page for a form post, the degraded turn
        shape for JSON, like retain's."""
        if self._is_form_submit():
            self._send_error_page(status, "Reflect", cause)
            return
        self._send_json(200, {"status": "degraded", "cause": cause})
