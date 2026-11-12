"""Host-side execution of Class D plugin data sources.

A declarative manifest promises data (``excel-watch`` over a scoped
glob) and a render model (``ui-schema`` with bindings). This module is
the half that makes the promise real for the types the host can run:
it resolves the declared glob against the workspace, reuses the
built-in excel pipeline unchanged (shadow copy before parse, SQLite
row-hash snapshots, the T-24h multiset diff), and binds the result
into the widget's ui-schema render model.

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

from agentdesk.excel.watcher import Adapters, ExcelWatch

# The binding vocabulary: values the host computes for a widget render.
# Anything a ui-schema asks for outside this set renders as nothing
# rather than an invented number.
BINDINGS = ("delta24h", "addedCount", "removedCount", "unchangedCount",
            "rowsSeen", "windowNote", "file")

EXECUTABLE_TYPES = ("excel-watch",)


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
    detaches as plugins install, update, disable and uninstall, and the
    runner only ever touches files under each plugin's own data dir and
    the workspace globs the manifest declared (and the user consented
    to) at install.
    """

    def __init__(self, workspace_dir: Path, adapters: Adapters | None = None,
                 interval_s: float | None = None) -> None:
        self.workspace_dir = Path(workspace_dir)
        self._adapters = adapters
        self._interval_s = interval_s
        self._watches: dict[str, ExcelWatch] = {}
        self._manifests: dict[str, dict] = {}
        self._dirs: dict[str, Path] = {}

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
        return plugin_id in self._watches

    def status(self, plugin_id: str) -> dict:
        """The plugin's source status: file presence and poll state, honest."""
        if plugin_id in self._watches:
            return self._watch_status(plugin_id)
        return self._attention("data source has not run")

    def retest(self, plugin_id: str) -> dict:
        """One poll right now; the amber card's button lands here."""
        watch = self._watches.get(plugin_id)
        if watch is None:
            return self.status(plugin_id)
        watch.retest()
        return self._watch_status(plugin_id)

    def payload(self, plugin_id: str) -> dict | None:
        """The bound ui-schema render model, or None when unbindable.

        Only whitelisted element kinds and known bindings survive: a
        plugin cannot smuggle markup in, and an unbindable ui-schema
        renders as nothing rather than an invented number.
        """
        if plugin_id not in self._watches:
            return None
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
        schema = self._load_ui_schema(base, render)
        if schema is None:
            return None
        status = self._watch_status(plugin_id)
        bindings = self._bindings(status)
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
