"""The three-step tracker setup: open a file, confirm columns, done.

Suggest is a button on the column step. It does not write a config.
"""

from __future__ import annotations

from agentdesk.plugins.config import ConfigError, InstanceStore
from agentdesk.plugins.preview import preview_table
from agentdesk.plugins.suggest import build_suggestion_request, heuristic, propose_columns

TRACKER_ID = "excel-report"
JOB = "Track one series from this workbook: a label column and a value column."


def store_for(runtime, cap: int) -> InstanceStore:
    return InstanceStore(runtime.data_dir, runtime.workspace_dir, cap=cap)


def ensure_instance(store: InstanceStore, instance_id: str, name: str, good: str = "up") -> dict:
    try:
        return store.read(TRACKER_ID, instance_id)
    except ConfigError:
        return store.create(TRACKER_ID, instance_id, name or instance_id, good=good)


def pick(runtime, cap: int, instance_id: str, name: str, pick_workbook) -> dict:
    store = store_for(runtime, cap)
    ensure_instance(store, instance_id, name)
    if pick_workbook is None:
        raise ConfigError("config:no-picker", "The file picker is not available.")
    chosen = pick_workbook()
    if not chosen:
        raise ConfigError("config:cancelled", "No file was opened.")
    store.stage_file(TRACKER_ID, instance_id, chosen)
    document = store.read(TRACKER_ID, instance_id)
    preview = preview_table(document["source"]["path"], sheet=None, header_row=1, range_text=None)
    return {"instance": document, "preview": preview, "step": "columns"}


def stage(runtime, cap: int, instance_id: str, name: str, path: str) -> dict:
    store = store_for(runtime, cap)
    ensure_instance(store, instance_id, name)
    store.stage_file(TRACKER_ID, instance_id, path)
    document = store.read(TRACKER_ID, instance_id)
    preview = preview_table(document["source"]["path"], sheet=None, header_row=1, range_text=None)
    return {"instance": document, "preview": preview, "step": "columns"}


def preview(runtime, cap: int, instance_id: str, *, sheet=None, header_row=1, range_text=None) -> dict:
    store = store_for(runtime, cap)
    document = store.read(TRACKER_ID, instance_id)
    source = document.get("source") or {}
    if not source.get("path"):
        raise ConfigError("config:missing-file", "Open a file first.")
    table = preview_table(source["path"], sheet=sheet, header_row=header_row, range_text=range_text)
    source["sheet"] = table["sheet"]
    source["headerRow"] = table["headerRow"]
    source["range"] = range_text
    document["source"] = source
    store._write(store._config_path(TRACKER_ID, instance_id), document)
    return {"preview": table, "step": "columns"}


def suggest(runtime, cap: int, instance_id: str, *, headers_only: bool, complete) -> dict:
    store = store_for(runtime, cap)
    document = store.read(TRACKER_ID, instance_id)
    source = document.get("source") or {}
    if not source.get("path"):
        raise ConfigError("config:missing-file", "Open a file first.")
    table = preview_table(
        source["path"], sheet=source.get("sheet"),
        header_row=source.get("headerRow") or 1, range_text=source.get("range"),
    )
    request, note = build_suggestion_request(
        job=JOB, sheet=table["sheet"], headers=table["headers"],
        rows=table["rows"], headers_only=headers_only, path=source["path"],
    )
    if complete is None:
        proposal = heuristic(table["headers"], table["rows"])
        return {"disclosure": note, "proposal": proposal, "error": ""}
    try:
        proposal = propose_columns(request, complete)
    except ConfigError:
        proposal = heuristic(table["headers"], table["rows"])
    return {"disclosure": note, "proposal": proposal, "error": ""}


def confirm(runtime, cap: int, instance_id: str, tracking: dict, *, suggested: bool,
            header_row=None, range_text=None, name: str | None = None) -> dict:
    store = store_for(runtime, cap)
    document = store.read(TRACKER_ID, instance_id)
    source = dict(document.get("source") or {})
    if header_row:
        source["headerRow"] = int(header_row)
    if range_text is not None:
        source["range"] = range_text or None
    if name and str(name).strip():
        document["name"] = str(name).strip()
    document["source"] = source
    store._write(store._config_path(TRACKER_ID, instance_id), document)
    saved = store.confirm(TRACKER_ID, instance_id, tracking, suggested=suggested)
    return {"instance": saved, "step": "done"}


def accept_outside(runtime, cap: int, instance_id: str) -> dict:
    store = store_for(runtime, cap)
    return store.accept_outside(TRACKER_ID, instance_id)
