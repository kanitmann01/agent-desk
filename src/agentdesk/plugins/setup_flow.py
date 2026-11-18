"""The per-instance setup flow: open a file, confirm columns, done.

Any installed plugin whose manifest declares the workbook config kind
is served by these helpers; the plugin id is a parameter, and every
call writes under that plugin's own namespace in the instance store.
Suggest is a button on the column step. It does not write a config.
"""

from __future__ import annotations

from agentdesk.plugins.config import ConfigError, InstanceStore
from agentdesk.plugins.preview import preview_table
from agentdesk.plugins.suggest import (
    build_evaluation_request,
    build_suggestion_request,
    evaluate_choice,
    heuristic,
    propose_columns,
)

JOB = "Track one series from this workbook: a label column and a value column."


def store_for(runtime, cap: int) -> InstanceStore:
    """Construct the instance store these helpers read and write through.

    ``cap`` is the plugin's own instance limit and travels with every call, so two
    plugins can allow different numbers of instances.
    """
    return InstanceStore(runtime.data_dir, runtime.workspace_dir, cap=cap)


def ensure_instance(store: InstanceStore, instance_id: str, name: str, plugin_id: str,
                    good: str = "up") -> dict:
    """Return the instance config, creating it the first time it is needed.

    Any config error on the read counts as "not created yet" and turns into a create,
    which can still fail on the cap or on an unsafe id. ``name`` is a display label
    and falls back to the instance id.
    """
    try:
        return store.read(plugin_id, instance_id)
    except ConfigError:
        return store.create(plugin_id, instance_id, name or instance_id, good=good)


def pick(runtime, cap: int, instance_id: str, name: str, pick_workbook,
         plugin_id: str) -> dict:
    """Run the file picker and return the instance with a preview of its first rows.

    The chosen file is staged before the preview, so an instance exists even when the
    user cancels and can be pointed at a file later. Raises ``config:no-picker`` when
    the runtime supplied no picker and ``config:cancelled`` when the user closed it.
    """
    store = store_for(runtime, cap)
    ensure_instance(store, instance_id, name, plugin_id=plugin_id)
    if pick_workbook is None:
        raise ConfigError("config:no-picker", "The file picker is not available.")
    chosen = pick_workbook()
    if not chosen:
        raise ConfigError("config:cancelled", "No file was opened.")
    store.stage_file(plugin_id, instance_id, chosen)
    document = store.read(plugin_id, instance_id)
    preview = preview_table(document["source"]["path"], sheet=None, header_row=1, range_text=None)
    return {"instance": document, "preview": preview, "step": "columns"}


def stage(runtime, cap: int, instance_id: str, name: str, path: str,
          plugin_id: str) -> dict:
    """Stage a path the user already knows as the instance's source.

    The same result as ``pick`` without the dialog; the store validates the path, so a
    missing or unsupported file raises before anything is previewed.
    """
    store = store_for(runtime, cap)
    ensure_instance(store, instance_id, name, plugin_id=plugin_id)
    store.stage_file(plugin_id, instance_id, path)
    document = store.read(plugin_id, instance_id)
    preview = preview_table(document["source"]["path"], sheet=None, header_row=1, range_text=None)
    return {"instance": document, "preview": preview, "step": "columns"}


def upload(runtime, cap: int, instance_id: str, name: str, raw: bytes, filename: str,
           plugin_id: str) -> dict:
    store = store_for(runtime, cap)
    ensure_instance(store, instance_id, name, plugin_id=plugin_id)
    path = store.store_upload(plugin_id, instance_id, filename, raw)
    store.stage_file(plugin_id, instance_id, path)
    store.accept_outside(plugin_id, instance_id)
    document = store.read(plugin_id, instance_id)
    preview = preview_table(document["source"]["path"], sheet=None, header_row=1, range_text=None)
    return {"instance": document, "preview": preview, "step": "columns"}


def preview(runtime, cap: int, instance_id: str, *, sheet=None, header_row=1, range_text=None,
            plugin_id: str) -> dict:
    """Preview the file again with a different sheet, header row or range.

    The selection is written to the config only after the preview succeeds, and the
    instance stays unconfirmed: choosing what to look at is separate from confirming
    what to track. Raises ``config:missing-file`` when no file is staged.
    """
    store = store_for(runtime, cap)
    document = store.read(plugin_id, instance_id)
    source = document.get("source") or {}
    if not source.get("path"):
        raise ConfigError("config:missing-file", "Open a file first.")
    table = preview_table(source["path"], sheet=sheet, header_row=header_row, range_text=range_text)
    source["sheet"] = table["sheet"]
    source["headerRow"] = table["headerRow"]
    source["range"] = range_text
    document["source"] = source
    store._write(store._config_path(plugin_id, instance_id), document)
    return {"preview": table, "step": "columns"}


def evaluate(runtime, cap: int, instance_id: str, tracking: dict, *, complete,
             plugin_id: str) -> dict:
    """One model opinion on the choice already on screen. Never raises for
    a model failure: the verdict says unchecked and confirm still works."""
    store = store_for(runtime, cap)
    document = store.read(plugin_id, instance_id)
    source = document.get("source") or {}
    if not source.get("path"):
        raise ConfigError("config:missing-file", "Open a file first.")
    table = preview_table(
        source["path"], sheet=source.get("sheet"),
        header_row=source.get("headerRow") or 1, range_text=source.get("range"),
        limit=500,
    )
    choice = {
        "labelColumn": str((tracking or {}).get("labelColumn") or ""),
        "valueColumn": str((tracking or {}).get("valueColumn") or ""),
        "rows": [index for index in ((tracking or {}).get("rows") or []) if isinstance(index, int)],
    }
    request, note = build_evaluation_request(
        job=JOB, sheet=table["sheet"], headers=table["headers"], rows=table["rows"],
        choice=choice, row_count=len(table["rows"]),
    )
    result = evaluate_choice(request, complete)
    return {"disclosure": note, **result, "error": None}


def suggest(runtime, cap: int, instance_id: str, *, headers_only: bool, complete,
            plugin_id: str) -> dict:
    """Propose a label column, value column and aggregate for the open file.

    With no model endpoint, or when the endpoint raises ``config:bad-*``, the
    heuristic proposes instead and the call still succeeds, so Suggest never blocks
    the step. ``headers_only`` trims the request to column names; the returned
    disclosure sentence says what actually left the machine.
    """
    store = store_for(runtime, cap)
    document = store.read(plugin_id, instance_id)
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
            header_row=None, range_text=None, name: str | None = None,
            plugin_id: str) -> dict:
    """Save the header row, range, name and column choice, then confirm the instance.

    The source edits are written before ``InstanceStore.confirm`` runs, because that
    call validates the row selection against the stored source; a rejected selection
    therefore leaves the new source in place and the instance unconfirmed.
    """
    store = store_for(runtime, cap)
    document = store.read(plugin_id, instance_id)
    source = dict(document.get("source") or {})
    if header_row:
        source["headerRow"] = int(header_row)
    if range_text is not None:
        source["range"] = range_text or None
    if name and str(name).strip():
        document["name"] = str(name).strip()
    document["source"] = source
    store._write(store._config_path(plugin_id, instance_id), document)
    saved = store.confirm(plugin_id, instance_id, tracking, suggested=suggested)
    return {"instance": saved, "step": "done"}


def accept_outside(runtime, cap: int, instance_id: str,
                   plugin_id: str) -> dict:
    """Accept the staged file even though it lives outside the workspace.

    A pass-through to the store: no file is read, only the grant written, and it is
    that grant which later lets confirm and the readers open the file.
    """
    store = store_for(runtime, cap)
    return store.accept_outside(plugin_id, instance_id)
