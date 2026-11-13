"""Host-side execution of Class D plugin data sources.

A declarative manifest promises data (``excel-watch`` over a scoped
glob) and a render model (``ui-schema`` with bindings). This module is
the half that makes the promise real for the types the host can run:
it resolves the declared glob against the workspace, reuses the
built-in excel pipeline unchanged (shadow copy before parse, SQLite
row-hash snapshots, the T-24h multiset diff), and binds the result
into the widget's ui-schema render model. The pipeline-backed types
read the same shared pipelines the dashboard's built-in cards use:
``calendar-read`` binds today's facts from the calendar bridge (its
day view, which never asks the model), ``mail-digest`` binds
header-only counts from the mail pipeline (the Message record has no
body field by construction, so no binding could carry one), and
``research-brief`` binds the latest stored sourced answer (a read of
the local store; no endpoint call happens anywhere in the plugin
path).

Data source types the host cannot execute yet keep their probe
semantics: the runner simply does not attach, the runtime keeps
serving the probe's file-presence status, and no bound payload is
produced. Every plugin that does attach gets its own store file inside
its own data dir, so uninstall and purge remove exactly what the
plugin wrote.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from glob import glob
from pathlib import Path

from agentdesk.assistant.research_store import ResearchStore
from agentdesk.calendar.watcher import (
    STATE_CLEAR,
    STATE_EMPTY,
    STATE_HEALTHY,
    CalendarBridge,
)
from agentdesk.excel.watcher import Adapters, ExcelWatch
from agentdesk.mail.watcher import STATE_ERROR, STATE_UNCONFIGURED, MailWatch

# The binding vocabulary, by data source type: the values the host
# computes for a widget render. A ui-schema element whose binding is
# not in its own source's set renders as nothing rather than an
# invented number.
#   excel-watch:   delta24h, addedCount, removedCount, unchangedCount,
#                  rowsSeen, file, windowNote
#   calendar-read: nextEventTitle, nextEventTime, eventsToday, windowNote
#   mail-digest:   messages, threads, topSenders, windowNote
#                  (header counts only; the mail Message record has no
#                  body field by construction)
#   research-brief: summary, sourcesCount, answeredAt, windowNote
BINDINGS = ("delta24h", "addedCount", "removedCount", "unchangedCount",
            "rowsSeen", "windowNote", "file",
            "nextEventTitle", "nextEventTime", "eventsToday",
            "messages", "threads", "topSenders",
            "summary", "sourcesCount", "answeredAt")

# Sources whose data lives in a shared built-in pipeline rather than a
# workspace glob: the runner reads the pipeline the dashboard's own
# cards use, and their honest states come from the pipeline itself.
PIPELINE_TYPES = ("calendar-read", "mail-digest", "research-brief")

EXECUTABLE_TYPES = ("excel-watch",) + PIPELINE_TYPES

CALENDAR_WINDOW_NOTE = (
    "The next commitment and today's count, from the calendar file your "
    "flow syncs."
)

MAIL_WINDOW_NOTE = (
    "Counts cover the last 24 hours of message headers; bodies are "
    "never read."
)

RESEARCH_WINDOW_NOTE = (
    "The latest stored research answer; showing it made no endpoint call."
)


def _delta_summary(delta: dict | None) -> str:
    if delta is None:
        return "First snapshot taken; changes show on the next refresh."
    added = len(delta.get("added", []))
    removed = len(delta.get("removed", []))
    if added == 0 and removed == 0:
        return "No changes in the last 24 hours."
    parts = []
    if added:
        parts.append(f"{added} new")
    if removed:
        parts.append(f"{removed} removed")
    return ", ".join(parts) + " rows."


def _window_note(delta: dict | None) -> str:
    if delta is None:
        return "The first snapshot is the baseline; the next poll diffs against it."
    return "Compared with the snapshot from about 24 hours ago."


def _iso(ts: float | None) -> str:
    if ts is None:
        return datetime.now().isoformat(timespec="seconds")
    return datetime.fromtimestamp(float(ts)).isoformat(timespec="seconds")


class PluginWidgetRunner:
    """Runs installed plugins' widget data sources; one watch per plugin.

    The runner owns no lifecycle: the plugin runtime attaches and
    detaches as plugins install, update, disable and uninstall. An
    excel-watch source runs over each plugin's own data dir and the
    workspace glob the manifest declared (and the user consented to) at
    install; the pipeline-backed types read the shared calendar bridge,
    mail watcher and research store the server wired in, and write
    nothing at all.
    """

    def __init__(self, workspace_dir: Path, adapters: Adapters | None = None,
                 interval_s: float | None = None, *,
                 calendar: CalendarBridge | None = None,
                 mail: MailWatch | None = None,
                 research: ResearchStore | None = None) -> None:
        self.workspace_dir = Path(workspace_dir)
        self._adapters = adapters
        self._interval_s = interval_s
        self._watches: dict[str, ExcelWatch] = {}
        self._manifests: dict[str, dict] = {}
        self._dirs: dict[str, Path] = {}
        # The shared pipelines the binding types read, the same objects
        # the dashboard's built-in cards use. None is honest: the card
        # goes amber naming what is missing rather than inventing data.
        # The server wires these (and rewires mail when its watcher is
        # rebuilt by the settings toggle), the way it wires the watches'
        # audit hooks.
        self.calendar = calendar
        self.mail = mail
        self.research = research
        self._pipelines: dict[str, str] = {}

    # ---- attachment ----

    def attach(self, plugin_id: str, manifest: dict, version_dir: Path,
               data_dir: Path) -> dict:
        """Point the runner at one installed plugin's active version.

        Returns the plugin's current source status, the same dict shape
        the runtime's probe produces, so callers treat them alike. A
        data source the host cannot execute does not attach: the
        returned status says so and the runtime keeps probe semantics
        for that plugin. Re-attaching replaces any previous watch.
        """
        self.detach(plugin_id)
        self._manifests[plugin_id] = manifest
        self._dirs[plugin_id] = Path(version_dir)
        widgets = manifest.get("contributes", {}).get("widgets", [])
        if not widgets:
            return self._attention("plugin contributes no widget")
        source = widgets[0].get("dataSource", {}) if isinstance(widgets[0], dict) else {}
        source_type = str(source.get("type", ""))
        if source_type in PIPELINE_TYPES:
            # Pipeline-backed sources have no glob of their own: their
            # truth is the shared pipeline's state, read live.
            self._pipelines[plugin_id] = source_type
            return self._pipeline_status(plugin_id)[0]
        pattern = str(source.get("file", "")).replace(
            "${workspace}", str(self.workspace_dir))
        if not pattern:
            return self._attention("data source has no file")
        matches = sorted(glob(pattern))
        if not matches:
            return self._attention(f"no file matches {source.get('file')}")
        if source_type not in EXECUTABLE_TYPES:
            # Probe parity: the file is there, but the host runs only
            # excel-watch today. Fresh file presence, no bound payload.
            return {"status": "fresh", "cause": "",
                    "checked_at": _iso(None), "file": Path(matches[0]).name}
        watch = self._new_watch(plugin_id, data_dir)
        self._watches[plugin_id] = watch
        watch.register(matches[0])
        return self._watch_status(plugin_id)

    def detach(self, plugin_id: str) -> None:
        watch = self._watches.pop(plugin_id, None)
        if watch is not None:
            watch.stop_polling()
            try:
                watch.conn.close()
            except Exception:  # noqa: BLE001 - closing must never raise
                pass
        self._pipelines.pop(plugin_id, None)
        self._manifests.pop(plugin_id, None)
        self._dirs.pop(plugin_id, None)

    def _new_watch(self, plugin_id: str, data_dir: Path) -> ExcelWatch:
        """One excel pipeline per plugin, over the plugin's own data dir."""
        store_dir = Path(data_dir)
        store_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(store_dir / "widget.sqlite3", check_same_thread=False)
        if self._adapters is not None:
            return ExcelWatch(conn, adapters=self._adapters,
                              source=f"plugin:{plugin_id}")
        return ExcelWatch(conn, source=f"plugin:{plugin_id}")

    # ---- observation ----

    def attached(self, plugin_id: str) -> bool:
        return plugin_id in self._watches or plugin_id in self._pipelines

    def status(self, plugin_id: str) -> dict:
        """The plugin's source status: file presence and poll state, honest."""
        if plugin_id in self._watches:
            return self._watch_status(plugin_id)
        if plugin_id in self._pipelines:
            return self._pipeline_status(plugin_id)[0]
        return self._attention("data source has not run")

    def retest(self, plugin_id: str) -> dict:
        """One poll right now; the amber card's button lands here."""
        watch = self._watches.get(plugin_id)
        if watch is not None:
            watch.retest()
            return self._watch_status(plugin_id)
        source_type = self._pipelines.get(plugin_id)
        if source_type == "calendar-read" and self.calendar is not None:
            # One poll of the shared bridge, breakdown-free: a plugin
            # card's re-test must never spend an endpoint request, so
            # the poll skips the breakdown entirely (cache included).
            # The built-in card's own re-test keeps its breakdown.
            self.calendar.poll(breakdown=False)
        return self.status(plugin_id)

    def payload(self, plugin_id: str) -> dict | None:
        """The bound ui-schema render model, or None when unbindable.

        Only whitelisted element kinds and known bindings survive: a
        plugin cannot smuggle markup in, and an unbindable ui-schema
        renders as nothing rather than an invented number.
        """
        if not self.attached(plugin_id):
            return None
        schema = self._schema_for(plugin_id)
        if schema is None:
            return None
        if plugin_id in self._watches:
            status = self._watch_status(plugin_id)
            bindings = self._bindings(status)
        else:
            status, bindings = self._pipeline_status(plugin_id)
        return self._render(schema, status, bindings)

    def card(self, plugin_id: str) -> dict:
        """One source read for both halves of a dashboard card: its
        status and its bound payload, computed from a single
        (status, bindings) pass (#75 review). Reading them separately
        would read and parse a pipeline twice per view, the mail folder
        included."""
        if plugin_id in self._watches:
            status = self._watch_status(plugin_id)
            bindings = self._bindings(status)
        elif plugin_id in self._pipelines:
            status, bindings = self._pipeline_status(plugin_id)
        else:
            return {"status": self._attention("data source has not run"),
                    "payload": None}
        schema = self._schema_for(plugin_id)
        payload = self._render(schema, status, bindings) if schema else None
        return {"status": status, "payload": payload}

    def start_polling(self, plugin_id: str) -> None:
        watch = self._watches.get(plugin_id)
        if watch is not None:
            watch.start_polling()

    def start_all_polling(self) -> None:
        for watch in self._watches.values():
            watch.start_polling()

    def stop_all(self) -> None:
        for plugin_id in list(self._watches):
            self.detach(plugin_id)

    # ---- internals ----

    def _schema_for(self, plugin_id: str) -> dict | None:
        """The widget's ui-schema document, or None when unrenderable."""
        base = self._dirs.get(plugin_id)
        manifest = self._manifests.get(plugin_id)
        if manifest is None or base is None:
            return None
        widgets = manifest.get("contributes", {}).get("widgets", [])
        if not widgets or not isinstance(widgets[0], dict):
            return None
        render = widgets[0].get("render", {})
        if not isinstance(render, dict) or render.get("type") != "ui-schema":
            return None
        return self._load_ui_schema(base, render)

    def _render(self, schema: dict, status: dict, bindings: dict) -> dict:
        """Bind values into the whitelisted element kinds. A binding
        outside the source's own set renders as nothing rather than an
        invented number."""
        elements = []
        for element in schema.get("elements", []):
            if not isinstance(element, dict):
                continue
            kind = str(element.get("type", ""))
            if kind == "metric":
                value = bindings.get(str(element.get("binding", "")))
                if value is None:
                    continue
                elements.append({"kind": "metric",
                                 "label": str(element.get("label", "")),
                                 "value": str(value)})
            elif kind == "text":
                if "binding" in element:
                    text = bindings.get(str(element.get("binding", "")))
                    if text is None:
                        continue
                else:
                    text = element.get("text", "")
                elements.append({"kind": "text", "text": str(text)})
        return {"elements": elements, "status": status["status"],
                "cause": status["cause"], "checked_at": status["checked_at"]}

    def _load_ui_schema(self, base: Path, render: dict) -> dict | None:
        name = str(render.get("file", ""))
        if not name.endswith(".json"):
            return None
        try:
            document = json.loads((base / name).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        return document if isinstance(document, dict) else None

    def _bindings(self, status: dict) -> dict:
        delta = status.get("delta")
        file_name = status.get("file", "")
        return {
            "delta24h": _delta_summary(delta),
            "addedCount": len(delta.get("added", [])) if delta else 0,
            "removedCount": len(delta.get("removed", [])) if delta else 0,
            "unchangedCount": delta.get("unchanged", 0) if delta else 0,
            "rowsSeen": status.get("rowsSeen", 0),
            "windowNote": _window_note(delta),
            "file": file_name,
        }

    # ---- the pipeline bindings ----

    def _pipeline_status(self, plugin_id: str) -> "tuple[dict, dict]":
        """(probe-shaped status, binding values) for a pipeline-backed
        source, read live from the shared pipeline. The values are
        empty whenever the status is not fresh: an amber pipeline binds
        nothing rather than a stale or invented number.
        """
        source_type = self._pipelines.get(plugin_id, "")
        if source_type == "calendar-read":
            return self._calendar_status()
        if source_type == "mail-digest":
            return self._mail_status()
        if source_type == "research-brief":
            return self._research_status()
        return self._attention("data source has not run"), {}

    def _research_status(self) -> "tuple[dict, dict]":
        """research-brief: the latest stored sourced answer, a pure read
        of the local research store (issue #64). No endpoint client
        exists anywhere in the runner, so the plugin path cannot make a
        model call even by accident."""
        store = self.research
        if store is None:
            return self._attention(
                "The research answer store is not available, so this "
                "card cannot show the latest answer."), {}
        latest = store.latest()
        if latest is None:
            return self._attention(
                "No research answer is stored yet. Ask something on the "
                "Research panel, then re-test."), {}
        answered_at = ""
        try:
            answered_at = datetime.fromtimestamp(
                float(latest.get("answeredTs", 0.0))).strftime("%Y-%m-%d %H:%M")
        except (OSError, OverflowError, ValueError):
            pass  # an undatable answer renders without the time, not wrongly
        values = {
            "summary": str(latest.get("summary", "")),
            "sourcesCount": len(latest.get("sources") or []),
            "windowNote": RESEARCH_WINDOW_NOTE,
        }
        if answered_at:
            values["answeredAt"] = answered_at
        return {"status": "fresh", "cause": "",
                "checked_at": _iso(None)}, values

    def _mail_status(self) -> "tuple[dict, dict]":
        """mail-digest: header-only counts from the mail pipeline's own
        read-only view, the same read the mail page makes (issue #64).
        The Message record has no body field by construction, so no
        binding here could carry one even by mistake."""
        watch = self.mail
        if watch is None:
            return self._attention(
                "The mail digest is not running. Turn it on in Settings "
                "and choose a folder, then re-test."), {}
        view = watch.view()
        state = str(view.get("state", ""))
        if state == STATE_UNCONFIGURED:
            return self._attention(
                "No mail folder is chosen yet. Turn on the mail digest "
                "in Settings and pick a folder, then re-test."), {}
        if state == STATE_ERROR:
            cause = str(view.get("cause") or
                        "the mail folder could not be read")
            return self._attention(cause), {}
        messages = view.get("messages") or []
        cutoff = watch.adapters.clock() - watch.digest_hours * 3600
        window = [m for m in messages if m.date_ts >= cutoff]
        senders: dict[str, int] = {}
        for message in window:
            senders[message.sender] = senders.get(message.sender, 0) + 1
        top = sorted(senders.items(), key=lambda item: (-item[1], item[0]))[:3]
        values = {
            "messages": len(window),
            "threads": len(view.get("digest") or []),
            "topSenders": ", ".join(
                f"{sender} ({count})" for sender, count in top) or "None",
            "windowNote": MAIL_WINDOW_NOTE,
        }
        return {"status": "fresh", "cause": "",
                "checked_at": _iso(None)}, values

    def _calendar_status(self) -> "tuple[dict, dict]":
        """calendar-read: today's facts from the bridge's day view, the
        same state machine the commitments card reads, without any
        model call (issue #64)."""
        bridge = self.calendar
        if bridge is None:
            return self._attention(
                "the calendar bridge is not available, so this card "
                "cannot read your calendar"), {}
        view = bridge.day_view()
        state = str(view.get("state", ""))
        if state == STATE_EMPTY:
            return self._attention(
                "No calendar data yet. Connect the calendar file on the "
                "calendar walkthrough page, then re-test."), {}
        if state not in (STATE_HEALTHY, STATE_CLEAR):
            # Stale, unreadable, or a state this host does not know:
            # amber with the bridge's own cause, never a bound number.
            cause = str(view.get("cause") or
                        "the calendar data needs attention")
            return self._attention(cause), {}
        key = view.get("keyEvent") or {}
        if key:
            # A real event with an empty subject is a busy slot: "Busy"
            # is the calendar flow's own default for a missing subject.
            # "Nothing left today" belongs to the clear day alone, where
            # there is no key event at all.
            title = str(key.get("subject") or "Busy")
        else:
            title = "Nothing left today"
        values = {
            "nextEventTitle": title,
            "eventsToday": int(view.get("eventsToday", 0)),
            "windowNote": CALENDAR_WINDOW_NOTE,
        }
        start = str(key.get("start", ""))
        if start:
            try:
                values["nextEventTime"] = datetime.fromisoformat(start).strftime("%H:%M")
            except ValueError:
                pass  # an unparseable time renders as nothing, not a guess
        return {"status": "fresh", "cause": "",
                "checked_at": _iso(None)}, values

    def _watch_status(self, plugin_id: str) -> dict:
        watch = self._watches[plugin_id]
        raw = watch.status()
        state = str(raw.get("state", ""))
        fresh = state in ("healthy", "first")
        cause = ""
        if not fresh:
            cause = str(raw.get("cause") or state
                        or "the data source needs attention")
        out = {
            "status": "fresh" if fresh else "attention",
            "cause": cause,
            "checked_at": _iso(raw.get("last_ok_ts")),
            "state": state,
        }
        if raw.get("path"):
            out["file"] = Path(str(raw["path"])).name
        if raw.get("delta") is not None:
            out["delta"] = raw["delta"]
        out["rowsSeen"] = raw.get("rowsSeen", 0)
        return out

    def _attention(self, cause: str) -> dict:
        return {"status": "attention", "cause": cause, "checked_at": _iso(None)}
