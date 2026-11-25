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
from datetime import datetime, timedelta
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
from agentdesk.mail.brief import brief as mail_brief
from agentdesk.mail.watcher import STATE_ERROR, STATE_UNCONFIGURED, MailWatch
from agentdesk.plugins.refresh import (
    MODE_CLOCK,
    MODE_HOOK,
    ReadingStore,
    update_mode,
    was_due_since,
)
from agentdesk.plugins.render import render_elements
from agentdesk.plugins.sources import (
    SOURCE_TYPES,
    SourceContext,
    cell_date,
    first_permitted_match,
    read_source,
    window_seconds,
)

# The binding vocabulary, by data source type: the values the host
# computes for a widget render. A ui-schema element whose binding is
# not in its own source's set renders as nothing rather than an
# invented number.
#   excel-watch:   delta24h, addedCount, removedCount, unchangedCount,
#                  direction, rowsSeen, file, windowNote, value,
#                  columns, rows, table, bucketTable, bucketRows,
#                  target, status, tone
#   calendar-read: nextEventTitle, nextEventTime, eventsToday, windowNote,
#                  rows, todayRows, upcoming, weekPoints, weekHours, items
#   mail-digest:   messages, threads, topSenders, windowNote,
#                  sendersRows, vipRows, waitingRows
#                  (header counts only; the mail Message record has no
#                  body field and no read flag by construction)
#   outlook-brief: messages, threads, threadRows, topEmailSubject,
#                  topEmailLine, topEmailWhy, replyOptions, windowNote
#                  (same header-only read; starters come from subjects)
#   research-brief: summary, sourcesCount, answeredAt, windowNote,
#                  sources, sourceRows, sourceTable
BINDINGS = ("delta24h", "addedCount", "removedCount", "unchangedCount",
            "direction", "rowsSeen", "windowNote", "file",
            "value", "target", "status", "tone", "points",
            "columns", "rows", "table", "bucketTable", "bucketRows",
            "nextEventTitle", "nextEventTime", "eventsToday",
            "todayRows", "upcoming", "weekPoints", "weekHours", "items",
            "messages", "threads", "topSenders", "sendersRows",
            "vipRows", "waitingRows",
            "threadRows", "topEmailSubject", "topEmailLine",
            "topEmailWhy", "replyOptions",
            "summary", "sourcesCount", "answeredAt",
            "sources", "sourceRows", "sourceTable")

EXCEL_ROWS_CAP = 8
EXCEL_TABLE_CAP = 20

# Sources whose data lives in a shared built-in pipeline rather than a
# workspace glob: the runner reads the pipeline the dashboard's own
# cards use, and their honest states come from the pipeline itself.
PIPELINE_TYPES = ("calendar-read", "mail-digest", "outlook-brief",
                  "research-brief")

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
    """Describe the snapshot delta as the one sentence a card shows.

    None means there is no earlier snapshot yet, which is not the same as no
    change: the first read says that changes show on the next refresh. Zero added
    and zero removed is reported as no change in the last 24 hours.
    """
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
    """Say what the delta was compared against, as the card's footnote.

    None means this snapshot is the baseline, so the note explains that the next
    poll is the one that diffs.
    """
    if delta is None:
        return "The first snapshot is the baseline; the next poll diffs against it."
    return "Compared with the snapshot from about 24 hours ago."


def _iso(ts: float | None) -> str:
    """Format a timestamp for a card as local ISO 8601 at whole seconds.

    None formats the current time: the caller is stamping a read that is happening
    now rather than reporting a time it does not have.
    """
    if ts is None:
        return datetime.now().isoformat(timespec="seconds")
    return datetime.fromtimestamp(float(ts)).isoformat(timespec="seconds")


def _as_number(value):
    """One cell as a number, or None. Currency marks and commas are fine."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    for mark in ("$", "\u20ac", "\u00a3", ","):
        text = text.replace(mark, "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _fmt_cell(value) -> str:
    """One cell as display text: thousands grouped, no fake precision."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        number = float(value)
        if number.is_integer():
            return f"{int(number):,}"
        return f"{number:,.2f}".rstrip("0").rstrip(".")
    return str(value).strip()


def _column_index(columns, name: str):
    """The index of a header by name, case- and space-insensitive."""
    wanted = str(name or "").strip().lower()
    if not wanted:
        return None
    for index, column in enumerate(columns):
        if str(column).strip().lower() == wanted:
            return index
    return None


def _cell(row, index):
    """Return one cell of a row by column index, or None when the row has no such cell."""
    if index is None or index < 0 or index >= len(row):
        return None
    return row[index]


def _bucket_labels(bounds):
    """Aging labels from the declared bounds: [30, 60, 90] -> 0-30 ... 90+."""
    labels = []
    previous = None
    for bound in bounds:
        labels.append(f"0-{bound}" if previous is None
                      else f"{previous + 1}-{bound}")
        previous = bound
    labels.append(f"{previous}+")
    return labels


def _bucket_index(days, bounds):
    """Return the index of the first aging bound the age does not exceed.

    An age above the last bound returns that bound's own index, so with the labels
    ``_bucket_labels`` produces, the overflow rows count into the last closed
    bucket and the open-ended final label stays empty.
    """
    for index, bound in enumerate(bounds):
        if days <= bound:
            return index
    return len(bounds) - 1


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
                 research: ResearchStore | None = None,
                 http_transport=None,
                 desk_state=None,
                 dependencies=None) -> None:
        """Wire a runner to the workspace whose files the plugins read.

        The collaborators are injection seams: ``adapters`` supplies the clock and the
        Excel read seams, ``calendar``/``mail``/``research`` are the shared pipelines the
        dashboard's own cards use, and ``http_transport``, ``desk_state`` and
        ``dependencies`` stand in for the network, the host callbacks and the installed
        manifests. Leaving any of them None is honest rather than broken: the affected
        source reads blank and its card names what is missing. Nothing is attached,
        polled or written here; that starts at ``attach``.
        """
        self.workspace_dir = Path(workspace_dir)
        self._adapters = adapters
        self._interval_s = interval_s
        self._watches: dict[str, ExcelWatch] = {}
        self._manifests: dict[str, dict] = {}
        # The last reading per plugin, and the clock the update modes read.
        # A scheduled or change-driven tile is answered from here, so opening
        # the desk cannot turn into a live read for it.
        self.readings = ReadingStore()
        self._clock = datetime.now
        # The modification-time stamp each file plugin was last read at.
        self._file_stamps: dict[str, str] = {}
        self._dirs: dict[str, Path] = {}
        self._data_dirs: dict[str, Path] = {}
        # Sources without a watch (everything except excel-watch) keep
        # their declaration here and are read through sources.read_source.
        self._sources: dict[str, dict] = {}
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
        # Injectable seams for sources that must not touch the network
        # or the user's files in tests: a transport, the desk-state
        # callbacks, and a provider of installed manifests for aggregate.
        self._http_transport = http_transport
        self._desk_state = desk_state
        self._dependency_provider = dependencies

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
        self._data_dirs[plugin_id] = Path(data_dir)
        plugin_config = manifest.get("config") if isinstance(manifest.get("config"), dict) else {}
        widgets = manifest.get("contributes", {}).get("widgets", [])
        if plugin_config.get("kinds"):
            source = {}
            if widgets and isinstance(widgets[0], dict):
                source = widgets[0].get("dataSource") or {}
            if not (isinstance(source, dict) and source.get("file")):
                # The file is chosen per instance. Attaching records the
                # plugin and reads nothing until a config is confirmed.
                self._sources[plugin_id] = source if isinstance(source, dict) else {}
                return {
                    "status": "setup",
                    "cause": "",
                    "checked_at": _iso(None),
                    "state": "setup",
                }
        if not widgets:
            return self._attention("This plugin adds no card to your dashboard.")
        source = widgets[0].get("dataSource", {}) if isinstance(widgets[0], dict) else {}
        source_type = str(source.get("type", ""))
        if source_type in PIPELINE_TYPES:
            # Pipeline-backed sources have no glob of their own: their
            # truth is the shared pipeline's state, read live.
            self._pipelines[plugin_id] = source_type
            self._sources[plugin_id] = source
            return self._status_dict(self._read_pair(plugin_id)[0])
        if source_type == "excel-watch":
            match = first_permitted_match(
                source.get("file", ""), self._source_context(plugin_id))
            if match is not None:
                watch = self._new_watch(plugin_id, data_dir)
                self._watches[plugin_id] = watch
                self._sources[plugin_id] = source
                watch.register(str(match))
                return self._status_dict(self._read_pair(plugin_id)[0])
            # No workbook: the reader reports the blank (or a declared
            # CSV fallback in its coarse state) without a watch.
            result = self._read_source_for(plugin_id, source)
            if result.state != "blank":
                self._sources[plugin_id] = source
            return self._status_dict(result)
        if source_type not in SOURCE_TYPES:
            return self._attention(f"unknown data source type: {source_type}")
        # Every other source type executes and attaches, including a
        # blank one: its card must say which file or connection is
        # missing rather than falling back to probe silence.
        self._sources[plugin_id] = source
        return self._status_dict(self._read_pair(plugin_id)[0])

    def detach(self, plugin_id: str) -> None:
        """Forget one plugin: stop its poller, close its store, drop its state.

        Safe for a plugin that never attached. Closing the SQLite connection is
        best-effort, because a detach runs on the way out of an uninstall and must not
        raise; the plugin's data directory is left in place, since purging it is the
        runtime's decision, not the runner's.
        """
        watch = self._watches.pop(plugin_id, None)
        if watch is not None:
            watch.stop_polling()
            try:
                watch.conn.close()
            except Exception:  # noqa: BLE001 - closing must never raise
                pass
        self.readings.clear(plugin_id)
        self._pipelines.pop(plugin_id, None)
        self._sources.pop(plugin_id, None)
        self._manifests.pop(plugin_id, None)
        self._dirs.pop(plugin_id, None)
        self._data_dirs.pop(plugin_id, None)

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

    @property
    def has_network(self) -> bool:
        """True when this runner carries an HTTP transport for plugin sources.

        Production builds the runner without one, so a plugin that reads the
        web is honestly unrunnable here; the marketplace reports the same
        fact so a surface never offers a path that cannot work.
        """
        return self._http_transport is not None

    def attached(self, plugin_id: str) -> bool:
        """Report whether the runner holds any state for the plugin.

        Any of the three registries counts: a polled watch, a pipeline-backed source, or
        a declared source read through ``read_source``. An ``excel-watch`` whose file is
        missing binds nothing and holds no entry, so it reports as not attached rather
        than as a blank read.
        """
        return (plugin_id in self._watches or plugin_id in self._pipelines
                or plugin_id in self._sources)

    def status(self, plugin_id: str) -> dict:
        """The plugin's source status, in the runtime's probe shape."""
        if not self.attached(plugin_id):
            return self._attention("data source has not run")
        return self._status_dict(self._read_pair(plugin_id)[0])

    def retest(self, plugin_id: str) -> dict:
        """Read the source once, now, and refresh the stored reading.

        The card's own button lands here. A scheduled or change-driven tile
        serves its stored reading, so a re-test that only read would be
        invisible to the card: the fresh result is stored, which is the whole
        point of asking for a re-test.
        """
        watch = self._watches.get(plugin_id)
        if watch is not None:
            watch.retest()
        source_type = self._pipelines.get(plugin_id)
        if source_type == "calendar-read" and self.calendar is not None:
            # One poll of the shared bridge, breakdown-free: a plugin
            # card's re-test must never spend an endpoint request, so
            # the poll skips the breakdown entirely (cache included).
            # The built-in card's own re-test keeps its breakdown.
            self.calendar.poll(breakdown=False)
        if self.attached(plugin_id):
            self._store_live(plugin_id)
        return self.status(plugin_id)

    def payload(self, plugin_id: str) -> dict | None:
        """The bound ui-schema render model, or None when unbindable.

        Only whitelisted element kinds and known bindings survive: a
        plugin cannot smuggle markup in, and an unbindable ui-schema
        renders as nothing rather than an invented number. Every
        payload carries the source's honest state beside its elements.
        """
        if not self.attached(plugin_id):
            return None
        schema = self._schema_for(plugin_id)
        if schema is None:
            return None
        result, bindings = self._read_pair(plugin_id)
        return self._render(plugin_id, schema, result, bindings)

    def card(self, plugin_id: str) -> dict:
        """One source read for both halves of a dashboard card: its
        status and its bound payload, computed from a single
        (status, bindings) pass (#75 review). Reading them separately
        would read and parse a pipeline twice per view, the mail folder
        included.

        A plugin whose tile updates on a clock or on a change serves its
        stored reading instead, so opening the home screen never re-reads what
        only its schedule or its own event is allowed to refresh. A "when I
        open the desk" tile, and every plugin installed before the update
        question existed, reads live as it always did. The first read of any
        mode is taken here, so a new tile is never empty.
        """
        if not self.attached(plugin_id):
            return {"status": self._attention("data source has not run"),
                    "payload": None}
        mode, _ = update_mode(self._manifests.get(plugin_id) or {})
        stored = self.readings.get(plugin_id)
        if mode in (MODE_CLOCK, MODE_HOOK) and stored is not None:
            return {"status": dict(stored.status),
                    "payload": stored.payload,
                    "asOf": stored.as_of,
                    "cached": True}
        card = self._read_card(plugin_id)
        reading = self.readings.put(plugin_id, card["status"], card["payload"])
        card["asOf"] = reading.as_of
        return card

    def _read_card(self, plugin_id: str) -> dict:
        """Read the source now and reduce it to a card's status and payload."""
        result, bindings = self._read_pair(plugin_id)
        schema = self._schema_for(plugin_id)
        payload = (self._render(plugin_id, schema, result, bindings)
                   if schema else None)
        return {"status": self._status_dict(result), "payload": payload}

    # ---- when a tile updates ---------------------------------------------

    def refresh_due(self, now: datetime | None = None) -> list[str]:
        """Refresh every scheduled plugin whose clock has come due.

        Returns the ids refreshed, which is what the minute tick and its
        tests both read. A scheduled plugin re-reads at most once per due
        minute, however often the tick runs.
        """
        now = now or self._clock()
        refreshed: list[str] = []
        for plugin_id, manifest in list(self._manifests.items()):
            mode, cron = update_mode(manifest)
            if mode != MODE_CLOCK or not self.attached(plugin_id):
                continue
            stored = self.readings.get(plugin_id)
            if stored is not None:
                last = datetime.fromisoformat(stored.as_of)
                if not was_due_since(cron, last, now):
                    continue
            self._store_live(plugin_id)
            refreshed.append(plugin_id)
        return refreshed

    def refresh_on_event(self, topic: str) -> list[str]:
        """Refresh the change-driven plugins whose watched topic just fired.

        A topic is ``workbook``, ``file``, ``calendar``, ``mail``, ``research``
        or ``manual``, derived from the source when the plugin was built. The
        reading is compared with the stored one, so a poll that found nothing
        new leaves the card and its as-of time exactly as they were.
        """
        refreshed: list[str] = []
        for plugin_id, manifest in list(self._manifests.items()):
            mode, declared = update_mode(manifest)
            if mode != MODE_HOOK or declared != topic or not self.attached(plugin_id):
                continue
            card = self._read_card(plugin_id)
            if self.readings.replace_if_changed(plugin_id, card["status"],
                                                card["payload"]):
                refreshed.append(plugin_id)
        return refreshed

    def _store_live(self, plugin_id: str) -> None:
        """Read the source now and store the result, without comparing."""
        card = self._read_card(plugin_id)
        self.readings.put(plugin_id, card["status"], card["payload"])

    def refresh_files_and_pipelines(self) -> list[str]:
        """Refresh every change tile that is not the workbook.

        File tiles refresh only when their file's modification time moved;
        the piped sources (calendar, mail, research) are re-read and stored
        only when the reading itself differs, since their poll loops have no
        per-plugin hook to call.
        """
        return (self.refresh_on_event("file", "manual", stamp_first=True)
                + self.refresh_on_event("calendar", "mail", "research"))

    def refresh_on_event(self, *topics: str, stamp_first: bool = False) -> list[str]:
        """Re-read the change tiles on these topics and store what changed.

        The topics are the ones a plugin's source declared: ``file``,
        ``manual``, ``calendar``, ``mail``, ``research``, or ``workbook``.
        With ``stamp_first`` a file source is compared by modification time
        before it is read at all, so a tick on an unchanged file costs a stat.
        """
        refreshed: list[str] = []
        for plugin_id, manifest in list(self._manifests.items()):
            mode, topic = update_mode(manifest)
            if mode != MODE_HOOK or topic not in topics:
                continue
            if not self.attached(plugin_id):
                continue
            if stamp_first:
                stamp = self._file_stamp(plugin_id)
                if stamp is None or self._file_stamps.get(plugin_id) == stamp:
                    continue
                self._file_stamps[plugin_id] = stamp
            card = self._read_card(plugin_id)
            if self.readings.replace_if_changed(plugin_id, card["status"],
                                                card["payload"]):
                refreshed.append(plugin_id)
        return refreshed

    def _file_stamp(self, plugin_id: str) -> str | None:
        """The modification-time signature of everything a file source reads.

        None means the source names no readable file yet, so there is nothing
        to compare and the tile is left to its own first read.
        """
        source = self._sources.get(plugin_id) or {}
        if source.get("type") == "manual-metric":
            declared = source.get("file")
            if not (isinstance(declared, str)
                    and declared.startswith("${pluginData}")):
                declared = "${pluginData}/manual.json"
        else:
            declared = source.get("file")
        if not isinstance(declared, str) or not declared:
            return None
        try:
            path = self._resolve_declared(plugin_id, declared)
        except Exception:  # noqa: BLE001 - an unreadable path is no stamp
            return None
        if path is None or not path.exists():
            return None
        try:
            return f"{path}:{path.stat().st_mtime_ns}"
        except OSError:
            return None

    def _resolve_declared(self, plugin_id: str, declared: str) -> Path | None:
        """Resolve one declared path against the workspace and plugin data."""
        text = declared.replace("${workspace}", str(self.workspace_dir))
        text = text.replace("${pluginData}",
                            str(self._data_dirs.get(plugin_id, self.workspace_dir)))
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = Path(self.workspace_dir) / candidate
        if any(char in str(candidate) for char in "*?"):
            matches = sorted(glob(str(candidate)))
            return Path(matches[0]) if matches else None
        return candidate

    # ---- source reads ----

    def _read_pair(self, plugin_id: str) -> "tuple":
        """Read the plugin's declared source once and return ``(result, bindings)``.

        The bindings are copied out of the result, so a caller cannot mutate the state
        the result was built from. A plugin with no declared source reads an empty
        declaration, which the reader answers as a blank rather than an error.
        """
        source = self._sources.get(plugin_id) or {}
        result = self._read_source_for(plugin_id, source)
        return result, dict(result.bindings)

    def _source_context(self, plugin_id: str) -> SourceContext:
        """The one context every read for this plugin uses.

        read_globs is the installed manifest's own filesystem.read list,
        so the reader can refuse a path no declared glob covers even
        though the manifest was validated elsewhere.
        """
        return SourceContext(
            plugin_id=plugin_id,
            workspace_dir=self.workspace_dir,
            data_dir=self._data_dirs.get(plugin_id, self.workspace_dir),
            now=datetime.now(),
            transport=self._http_transport,
            dependencies=self._dependency_map(),
            desk_state=self._desk_state,
            excel_bindings=self._excel_pair(plugin_id),
            pipeline_status=self._pipeline_pair(plugin_id),
            network_allow=self._network_allow(plugin_id),
            read_globs=self._read_globs(plugin_id),
        )

    def _read_globs(self, plugin_id: str) -> tuple:
        """Return the manifest's declared read globs as a tuple of strings.

        Only ``permissions.filesystem.read`` is consulted. An absent entry, or anything
        there other than a list of strings, yields an empty tuple, which the reader
        takes as no declared access and refuses paths accordingly.
        """
        manifest = self._manifests.get(plugin_id) or {}
        permissions = manifest.get("permissions")
        filesystem = (permissions.get("filesystem")
                      if isinstance(permissions, dict) else None)
        read_globs = (filesystem.get("read")
                      if isinstance(filesystem, dict) else None)
        if not isinstance(read_globs, list):
            return ()
        return tuple(item for item in read_globs if isinstance(item, str))

    def _read_source_for(self, plugin_id: str, source: dict):
        """Run one declared data source for a plugin under that plugin's own context.

        Every read builds a fresh context, so the permission globs, data directory,
        shared pipelines, desk callbacks and network allowlist all belong to this
        plugin. The source type is copied into the result's detail so a card can name
        the type even when the read comes back blank.
        """
        source_type = str(source.get("type", ""))
        result = read_source(source, self._source_context(plugin_id))
        result.detail.setdefault("type", source_type)
        return result

    def _now(self) -> datetime:
        """Return the runner's clock: the injected adapters' clock when there are adapters.

        Reads that compare a row's date against a declared window go through this, so a
        test can place the runner in time without patching ``datetime``.
        """
        if self._adapters is not None:
            return datetime.fromtimestamp(self._adapters.clock())
        return datetime.now()

    def _excel_pair(self, plugin_id: str):
        """Return the excel binding callback for a plugin, or None when it has no watch.

        The returned callable takes a source declaration and returns ``(status,
        bindings)``. It reads the watch's live status first, so the declared columns are
        only interpreted for a fresh read.
        """
        if plugin_id not in self._watches:
            return None

        def pair(source):
            """Read the watch and bind the workbook, or report why it cannot be bound.

            ``status`` is the probe-shaped dict here, not a ``SourceResult``; a status other
            than fresh returns it with no bindings, so an amber card cannot show numbers
            left over from an older read.
            """
            raw = self._watches[plugin_id].status()
            status = self._status_from_raw(raw)
            if status["status"] != "fresh":
                return status, {}
            return self._excel_bindings(
                source if isinstance(source, dict) else {}, raw, status)

        return pair

    def _excel_attention(self, reason: str, cause: str, raw: dict) -> dict:
        """Build the attention status for a workbook the runner cannot bind.

        ``reason`` is the machine-facing state and ``cause`` the sentence the user
        reads. ``checked_at`` comes from the watch's last successful poll, so an
        unbindable workbook still shows when it was last good.
        """
        return {
            "status": "attention",
            "cause": cause,
            "checked_at": _iso(raw.get("last_ok_ts")),
            "state": reason,
            "reason": reason,
        }

    def _excel_bindings(self, source: dict, raw: dict, status: dict):
        """Map the workbook's bounded grid by header name.

        The manifest names the columns (keyColumn, valueColumn,
        dateColumn); the reader's grid carries the header row, so the
        mapping is by name, case- and space-insensitive, never by
        position. A column the workbook does not have is a blank status
        naming it, never an empty card full of zeros.
        """
        grid = raw.get("grid") or {}
        columns = [str(cell) for cell in (grid.get("columns") or [])]
        grid_rows = [row for row in (grid.get("rows") or [])
                     if isinstance(row, (list, tuple))]
        base = self._bindings(status)
        base["columns"] = columns
        key_name = str(source.get("keyColumn", "") or "").strip()
        value_name = str(source.get("valueColumn", "") or "").strip()
        date_name = str(source.get("dateColumn", "") or "").strip()
        if not key_name and not value_name:
            # The legacy contract declares no columns: the card gets the
            # row count and the delta summary, nothing header-mapped.
            return status, base
        if not columns:
            return self._excel_attention(
                "missing-header",
                "The workbook has no header row yet, so the card cannot map "
                "columns by name.", raw), {}
        missing = [name for name in (key_name, value_name, date_name)
                   if name and _column_index(columns, name) is None]
        if missing:
            return self._excel_attention(
                "missing-column",
                f"The workbook has no column named {', '.join(missing)}. "
                f"Add it, or change the column name the widget asks for.",
                raw), {}
        key_at = _column_index(columns, key_name)
        value_at = _column_index(columns, value_name)
        date_at = _column_index(columns, date_name)
        now = self._now()
        window = source.get("window")
        cutoff_date = None
        if date_at is not None and window:
            cutoff_date = (now
                           - timedelta(seconds=window_seconds(window))).date()
        mapped = []
        for row in grid_rows:
            when = cell_date(_cell(row, date_at)) if date_at is not None else None
            if (cutoff_date is not None and when is not None
                    and when.date() < cutoff_date):
                continue
            mapped.append((row, when))
        mode = str(source.get("aggregate", "") or "").lower()
        if mode not in ("sum", "count", "avg", "latest", "min", "max"):
            mode = "count" if value_at is None else "sum"
        numbers = []
        if value_at is not None:
            for row, _ in mapped:
                number = _as_number(_cell(row, value_at))
                if number is not None:
                    numbers.append(number)
        if value_at is None:
            # No value column declared: the legacy row count, as before.
            value = int(status.get("rowsSeen", 0) or 0)
        elif mode == "count":
            value = len(mapped)
        elif not numbers:
            return self._excel_attention(
                "no-values",
                f"The workbook has no numeric values in the {value_name} "
                f"column, so there is nothing to total.", raw), {}
        elif mode == "sum":
            value = sum(numbers)
        elif mode == "avg":
            value = sum(numbers) / len(numbers)
        elif mode == "latest":
            value = numbers[-1]
        elif mode == "min":
            value = min(numbers)
        else:
            value = max(numbers)
        if isinstance(value, float):
            value = round(value, 2)
            if value.is_integer():
                value = int(value)
        rows = [
            {
                "primary": (_fmt_cell(_cell(row, key_at))
                            if key_at is not None else ""),
                "secondary": (_fmt_cell(_cell(row, value_at))
                              if value_at is not None else ""),
                "meta": when.strftime("%Y-%m-%d") if when is not None else "",
            }
            for row, when in mapped[:EXCEL_ROWS_CAP]
        ]
        table_columns = [name for name in (key_name, value_name, date_name)
                         if name]
        table_rows = []
        for row, when in mapped[:EXCEL_TABLE_CAP]:
            cells = []
            if key_at is not None:
                cells.append(_fmt_cell(_cell(row, key_at)))
            if value_at is not None:
                cells.append(_fmt_cell(_cell(row, value_at)))
            if date_at is not None:
                cells.append(when.strftime("%Y-%m-%d") if when else "")
            table_rows.append(cells)
        base["value"] = value
        target = _as_number(source.get("target"))
        if source.get("target") is not None and target is not None:
            good = str(source.get("targetGood", "down") or "down").lower()
            if good == "up":
                on_track = value >= target
                off_text = "below target"
            else:
                on_track = value <= target
                off_text = "over target"
            base["target"] = (int(target) if float(target).is_integer()
                              else target)
            base["status"] = "on track" if on_track else off_text
            base["tone"] = "ok" if on_track else "attention"
        else:
            base["status"] = f"Read {now.strftime('%H:%M')}"
            base["tone"] = "ok"
        bucket_table = []
        bucket_rows = []
        buckets = source.get("buckets")
        if isinstance(buckets, (list, tuple)) and date_at is not None:
            bounds = sorted({
                int(number) for number in (_as_number(item) for item in buckets)
                if number is not None
            })
            if bounds:
                labels = _bucket_labels(bounds)
                sums = [0.0] * len(labels)
                counts = [0] * len(labels)
                seen = [False] * len(labels)
                for row, when in mapped:
                    if when is None:
                        continue
                    days = max((now.date() - when.date()).days, 0)
                    index = _bucket_index(days, bounds)
                    counts[index] += 1
                    number = (_as_number(_cell(row, value_at))
                              if value_at is not None else None)
                    if number is not None:
                        sums[index] += number
                        seen[index] = True
                for index, label in enumerate(labels):
                    amount = _fmt_cell(round(sums[index], 2)) if seen[index] else ""
                    bucket_table.append([label, amount, str(counts[index])])
                    bucket_rows.append({
                        "primary": label,
                        "secondary": amount,
                        "meta": f"{counts[index]} invoices",
                    })
        base["rows"] = rows
        base["table"] = {"columns": table_columns, "rows": table_rows}
        base["bucketTable"] = bucket_table
        base["bucketRows"] = bucket_rows
        return status, base

    def _pipeline_pair(self, plugin_id: str):
        """Return the pipeline status callback for a plugin, or None when it backs none.

        The callback ignores the source it is handed and reads the plugin's pipeline
        live; ``read_source`` calls it once per read, which is what keeps a card's
        status and its values from describing two different reads.
        """
        if plugin_id not in self._pipelines:
            return None
        return lambda source_type: self._pipeline_status(plugin_id)

    def _dependency_map(self) -> dict:
        """Return the installed-manifest map that aggregate sources read through.

        ``dependencies`` may be a mapping or a callable returning one, so the runner can
        follow manifests that change while it runs. A callable that raises, or a value
        that is not a dict, reads as no dependencies: the aggregate then reports its
        dependency as missing instead of the runner failing.
        """
        provider = self._dependency_provider
        if callable(provider):
            try:
                loaded = provider()
            except Exception:  # noqa: BLE001 - a bad provider reads as none
                return {}
            return loaded if isinstance(loaded, dict) else {}
        return provider if isinstance(provider, dict) else {}

    def _network_allow(self, plugin_id: str) -> "tuple":
        """Return the host allowlist a plugin was granted for outbound reads.

        It comes from the manifest's ``optionalPermissions.network.allow``, present only
        when the user accepted that permission. Without it the tuple is empty and an
        ``http-get`` source reads blank instead of making a request.
        """
        manifest = self._manifests.get(plugin_id) or {}
        optional = manifest.get("optionalPermissions")
        network = optional.get("network") if isinstance(optional, dict) else None
        allow = network.get("allow") if isinstance(network, dict) else None
        return tuple(str(item) for item in (allow or [])
                     if isinstance(item, str))

    def _status_dict(self, result) -> dict:
        """Convert a source result into the probe-shaped status dict.

        Blank is the only state that becomes ``attention``: stale, coarse and partial
        reads are still shown, with their state kept in ``state`` so the card can say
        what is wrong with them. ``checked_at`` falls back to now when the read
        recorded no time, and ``file`` is the first matched file's name rather than
        its path, because the status is what a card displays.
        """
        status = "attention" if result.state == "blank" else "fresh"
        out = {
            "status": status,
            "cause": result.human if status == "attention" else "",
            "checked_at": result.as_of or _iso(None),
            "state": result.state,
            "reason": result.reason,
            "type": result.detail.get("type", ""),
            "files": list(result.files),
        }
        if result.files:
            out["file"] = Path(result.files[0]).name
        return out

    def _source_envelope(self, plugin_id: str, result) -> dict:
        """Say where a payload's values came from, beside the values themselves.

        The envelope carries the source type, the bound ``value``, the read time, the
        state and reason, and the files read, so a rendered element can be traced to
        the read behind it even when the card is showing stale or coarse data.
        """
        source = self._sources.get(plugin_id) or {}
        return {
            "type": str(source.get("type", result.detail.get("type", ""))),
            "value": result.bindings.get("value"),
            "asOf": result.as_of,
            "source": result.source,
            "state": result.state,
            "reason": result.reason,
            "human": result.human,
            "files": list(result.files),
        }

    def start_all_polling(self) -> None:
        """Start the poller of every attached watch.

        Only ``excel-watch`` sources have one, so the on-demand sources are untouched.
        Calling this after per-plugin ``start_polling`` starts the same pollers again.
        """
        for watch in self._watches.values():
            watch.start_polling()

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

    def _render(self, plugin_id: str, schema: dict, result,
                bindings: dict) -> dict:
        """Bind values into the ten whitelisted element kinds.

        A binding outside the source's own set renders as a blank element
        naming the missing binding, never an invented number. The legacy
        payload shape is unchanged for bound elements: the ok state is
        omitted so existing cards keep their exact element dicts. When the
        source itself is blank the whole card stays an honest empty list.
        The source envelope carries the honest state for every other case,
        stale/coarse/partial included.
        """
        status = self._status_dict(result)
        elements = render_elements(schema, bindings)
        if status["status"] != "fresh":
            elements = []
        else:
            elements = [
                {key: value for key, value in element.items()
                 if key not in ("state", "reason")}
                if element.get("state") == "ok"
                else element
                for element in elements
            ]
        return {"elements": elements, "status": status["status"],
                "cause": status["cause"], "checked_at": status["checked_at"],
                "source": self._source_envelope(plugin_id, result)}

    def _load_ui_schema(self, base: Path, render: dict) -> dict | None:
        """Load the widget's ui-schema document out of the plugin's version directory.

        Only a ``.json`` file is read. A missing, unreadable or non-object document
        returns None, which the runtime reads as nothing to render rather than as an
        error.
        """
        name = str(render.get("file", ""))
        if not name.endswith(".json"):
            return None
        try:
            document = json.loads((base / name).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        return document if isinstance(document, dict) else None

    def _bindings(self, status: dict) -> dict:
        """Return the binding values every excel card carries before any column is mapped.

        Counts come from the watch's delta and ``direction`` compares added with
        removed, so a card can speak of change without arithmetic of its own. ``value``
        and ``rowsSeen`` start as the row count and are replaced by the column-mapped
        read when the manifest declares columns.
        """
        delta = status.get("delta")
        file_name = status.get("file", "")
        added = len(delta.get("added", [])) if delta else 0
        removed = len(delta.get("removed", [])) if delta else 0
        if added > removed:
            direction = "up"
        elif added < removed:
            direction = "down"
        else:
            direction = "flat"
        return {
            "delta24h": _delta_summary(delta),
            "addedCount": added,
            "removedCount": removed,
            "unchangedCount": delta.get("unchanged", 0) if delta else 0,
            "direction": direction,
            "rowsSeen": status.get("rowsSeen", 0),
            "windowNote": _window_note(delta),
            "file": file_name,
            "value": status.get("rowsSeen", 0),
            "rows": [],
            "table": [],
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
            return self._calendar_status(plugin_id)
        if source_type == "mail-digest":
            return self._mail_status(plugin_id)
        if source_type == "outlook-brief":
            return self._outlook_status(plugin_id)
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
        # The store persists bare source strings, so the title column is
        # honestly empty; "used" is true by construction (these are the
        # answer's sources).
        source_rows = [
            {"primary": str(source), "secondary": "", "meta": "used"}
            for source in (latest.get("sources") or [])
        ]
        values = {
            "summary": str(latest.get("summary", "")),
            "sourcesCount": len(source_rows),
            "windowNote": RESEARCH_WINDOW_NOTE,
            "sources": source_rows,
            "sourceRows": source_rows,
            "sourceTable": [[row["primary"], "", "yes"] for row in source_rows],
            "rows": source_rows,
        }
        if answered_at:
            values["answeredAt"] = answered_at
        return {"status": "fresh", "cause": "",
                "checked_at": _iso(None)}, values

    def _mail_status(self, plugin_id: str = "") -> "tuple[dict, dict]":
        """mail-digest: header-only counts from the mail pipeline's own
        read-only view, the same read the mail page makes (issue #64).
        The Message record has no body field and no read flag by
        construction, so no binding here could carry either even by
        mistake; the VIP list filters senders the manifest declared."""
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
        sender_rows = [
            {"primary": sender, "secondary": str(count), "meta": ""}
            for sender, count in sorted(senders.items(),
                                          key=lambda item: (-item[1], item[0]))
        ]
        waiting_rows = [
            {"primary": str(item.get("thread", "")),
             "secondary": str(item.get("from", "")),
             "meta": f"{item.get('days', '')}d"}
            for item in (view.get("followUps") or []) if isinstance(item, dict)
        ]
        source = self._sources.get(plugin_id) or {}
        declared = source.get("vips")
        vips = [str(item).strip().lower()
                for item in (declared if isinstance(declared, (list, tuple))
                             else [])
                if str(item).strip()]
        if vips:
            # Substring match, case-insensitive: a manifest may name a
            # person ("Bhavya") or an address fragment ("@bank.com").
            vip_rows = [row for row in sender_rows
                        if any(vip in row["primary"].lower() for vip in vips)]
        else:
            vip_rows = []
        values = {
            "messages": len(window),
            "threads": len(view.get("digest") or []),
            "topSenders": ", ".join(
                f"{sender} ({count})" for sender, count in top) or "None",
            "windowNote": MAIL_WINDOW_NOTE,
            "sendersRows": sender_rows,
            # No read flag exists on the Message record, so no "unread"
            # binding is offered at all; VIPs are a declared filter over
            # the same header counts, empty until a manifest names any.
            "vipRows": vip_rows,
            "waitingRows": waiting_rows,
        }
        return {"status": "fresh", "cause": "",
                "checked_at": _iso(None)}, values

    def _outlook_status(self, plugin_id: str = "") -> "tuple[dict, dict]":
        """outlook-brief: the digest, the one message that matters and
        three openers, all from the same header-only folder read the mail
        page uses. No body is read and no model is called.

        Empty and unconfigured folders are attention states with copy that
        names the next action, never a zero dressed up as a reading.
        """
        watch = self.mail
        if watch is None:
            return self._attention(
                "The Outlook brief is not running. Turn on mail in Settings, "
                "choose the folder your .eml exports land in, then re-test."), {}
        view = watch.view()
        state = str(view.get("state", ""))
        if state == STATE_UNCONFIGURED:
            return self._attention(
                "No mail folder is chosen yet. Turn on mail in Settings and "
                "pick a folder, or run tools/export-outlook.ps1 -OutDir "
                "<folder> first."), {}
        if state == STATE_ERROR:
            cause = str(view.get("cause") or
                        "the mail folder could not be read")
            return self._attention(cause), {}
        messages = view.get("messages") or []
        if not messages:
            skipped = int(view.get("unparsedFiles") or 0)
            if skipped:
                return self._attention(
                    f"{skipped} .eml file(s) in the mail folder could not be "
                    "parsed. Re-export them with tools/export-outlook.ps1, "
                    "then re-test."), {}
            return self._attention(
                "The mail folder is empty. Export Outlook mail into it with "
                "tools/export-outlook.ps1 -OutDir <folder>, then re-test."), {}
        now = watch.adapters.clock()
        values = mail_brief(messages, now, watch.self_address,
                            hours=watch.digest_hours)
        return {"status": "fresh", "cause": "",
                "checked_at": _iso(None)}, values

    def _calendar_status(self, plugin_id: str = "") -> "tuple[dict, dict]":
        """calendar-read: today's facts from the bridge's day view, the
        same state machine the commitments card reads, without any
        model call (issue #64). plugin_id is part of the pipeline
        signature so both pipeline types read alike; the calendar
        bridge is shared and needs no per-plugin source."""
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
        today_rows = [row for row in (view.get("todayRows") or [])
                      if isinstance(row, dict)]
        upcoming_rows = [row for row in (view.get("upcoming") or [])
                         if isinstance(row, dict)]
        items = [item for item in (view.get("items") or [])
                 if isinstance(item, dict)]
        values = {
            "nextEventTitle": title,
            "eventsToday": int(view.get("eventsToday", 0)),
            "windowNote": CALENDAR_WINDOW_NOTE,
            "todayRows": today_rows,
            # The calendar-today card's "What is left" list reads rows.
            "rows": today_rows,
            "upcoming": upcoming_rows,
            "weekPoints": [int(point) for point in (view.get("weekPoints") or [])],
            "weekHours": float(view.get("weekHours", 0.0)),
            "items": items,
        }
        start = str(key.get("start", ""))
        if start:
            try:
                values["nextEventTime"] = datetime.fromisoformat(start).strftime("%H:%M")
            except ValueError:
                pass  # an unparseable time renders as nothing, not a guess
        return {"status": "fresh", "cause": "",
                "checked_at": _iso(None)}, values

    def _status_from_raw(self, raw: dict) -> dict:
        """Convert a watch's raw status into the probe-shaped status dict.

        Only ``healthy`` and ``first`` count as fresh; anything else becomes attention
        carrying the watch's cause, falling back to the state name and then to a
        generic sentence, so a card is never silent about why. ``path`` is reduced to a
        file name, and ``delta`` is passed through only when present, because an absent
        delta and an empty one mean different things.
        """
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
        """Build a not-yet-run status whose ``cause`` is the reason the user is shown.

        No ``state`` is reported: this describes the runner's own refusal, not a state
        the data source produced. ``checked_at`` stays empty because nothing ran, so
        the card cannot show the page load time as the plugin's last run.
        """
        return {"status": "attention", "cause": cause, "checked_at": ""}