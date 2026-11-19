"""Pure host-side rendering of ui-schema elements.

No plugin code runs here. render_elements maps a ui-schema document plus an
already-computed binding dict into the element DTOs the dashboard draws.
render_sample reads a v2 manifest's fixture from inside the plugin directory
and returns the same payload the executor emits.
"""

import json
import re
from pathlib import Path

# The ten element kinds, their direction and tone words: one owner in
# vocabulary, imported here so this module's renderers and the SPA agree.
from agentdesk.plugins.vocabulary import DIRECTIONS, ELEMENT_KINDS, TONES

_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")


class PluginRenderError(ValueError):
    """A ui-schema cannot be rendered (unknown kind, missing sample)."""

    code = "plugin:unknown-element"


def render_elements(schema: dict, bindings: dict) -> list[dict]:
    """Render every element in the schema; skip non-dict entries.

    Missing bindings produce a blank element with a reason, never a zero.
    Unknown element kinds are a hard error.
    """
    if not isinstance(schema, dict):
        return []
    elements = schema.get("elements")
    if not isinstance(elements, list):
        return []
    if not isinstance(bindings, dict):
        bindings = {}

    rendered: list[dict] = []
    for element in elements:
        if not isinstance(element, dict):
            continue
        kind = element.get("type")
        if not isinstance(kind, str) or kind not in ELEMENT_KINDS:
            raise PluginRenderError(f"unknown element kind: {kind}")
        try:
            rendered.append(_RENDERERS[kind](element, bindings))
        except PluginRenderError:
            raise
        except (TypeError, ValueError):
            # Malformed structured data yields a blank element, not a crash.
            rendered.append(_blank(kind, element, f"malformed {kind} element"))
    return rendered


# ---------------------------------------------------------------------------
# Value coercion helpers
# ---------------------------------------------------------------------------


def _string(value) -> str:
    """Coerce a scalar binding value to display text.

    None renders as an empty string, booleans as "true"/"false", and structured
    values (dict/list) as an empty string: a widget shows text, not a payload.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return ""
    return str(value)


def _number(value):
    """Coerce a numeric-looking value to an int or float.

    Returns None when no number can be read, including for booleans, which
    Python would otherwise accept as ints. Integer-looking strings become int so
    whole counts keep their exact digits.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            if _INTEGER_PATTERN.match(text):
                return int(text)
            return float(text)
        except (TypeError, ValueError):
            return None
    return None


def _direction(value) -> str:
    """Normalise a direction word to one of DIRECTIONS.

    Anything unrecognised renders as "flat" rather than failing the element.
    """
    text = _string(value).lower()
    return text if text in DIRECTIONS else "flat"


def _tone(value) -> str:
    """Normalise a tone word to one of TONES.

    Anything unrecognised renders as "ok" rather than failing the element.
    """
    text = _string(value).lower()
    return text if text in TONES else "ok"


def _boolean(value) -> bool:
    """Coerce a checklist flag to bool.

    Strings count as true for "1", "true", "yes", "done" and "on", and numbers
    count as true when nonzero. Everything else, including None, is false, so an
    absent flag reads as not done.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "done", "on")
    if isinstance(value, (int, float)):
        return value != 0
    return False


def _binding_name(element, key: str = "binding") -> str:
    """Return the element's binding name, or an empty string when it has none.

    The empty string is the sentinel for "unbound" downstream, which is why a
    non-string value is dropped instead of being stringified.
    """
    name = element.get(key)
    return name if isinstance(name, str) else ""


def _lookup(bindings: dict, name: str):
    """Return (value, found). A None value counts as no value."""
    if not name or name not in bindings:
        return None, False
    value = bindings[name]
    if value is None:
        return None, False
    return value, True


def _with_optional(target: dict, element: dict, key: str) -> dict:
    """Copy an optional string field from the schema element into the DTO.

    The field is only emitted when the element declares it, so absent optional
    fields stay absent instead of becoming empty ones. Returns the target so the
    caller can keep building the same dict.
    """
    if key in element:
        target[key] = _string(element.get(key))
    return target


# ---------------------------------------------------------------------------
# Renderers. Each returns the exact DTO for its kind.
# ---------------------------------------------------------------------------


def _render_metric(element, bindings) -> dict:
    """Render one labelled value.

    A bound value renders as state "ok"; a missing binding renders the label
    with an empty value, state "blank" and a reason, so the card can show why it
    is empty instead of claiming zero.
    """
    name = _binding_name(element)
    value, found = _lookup(bindings, name)
    dto = {"kind": "metric"}
    if found:
        dto["state"] = "ok"
        dto["value"] = _string(value)
    else:
        dto["state"] = "blank"
        dto["value"] = ""
        dto["reason"] = f"no value for binding {name}"
    dto["label"] = _string(element.get("label"))
    return dto


def _render_text(element, bindings) -> dict:
    """Render literal text, or the value of a binding.

    The presence of the "binding" key selects the bound form, even when the name
    is unusable: an element that points at nothing is blank, not literal.
    """
    if "binding" in element:
        name = _binding_name(element)
        value, found = _lookup(bindings, name)
        if found:
            text, state, reason = _string(value), "ok", ""
        else:
            text, state, reason = "", "blank", f"no value for binding {name}"
    else:
        literal = element.get("text")
        if literal is None:
            text, state, reason = "", "blank", "no text for text element"
        else:
            text, state, reason = _string(literal), "ok", ""
    dto = {"kind": "text", "state": state, "text": text}
    if reason:
        dto["reason"] = reason
    _with_optional(dto, element, "label")
    return dto


def _render_delta(element, bindings) -> dict:
    """Render a change value together with its direction and window.

    The direction is read from directionBinding when that resolves and otherwise
    stays "flat"; window is the schema's free-text period label, passed through
    as written.
    """
    name = _binding_name(element)
    value, found = _lookup(bindings, name)
    dto = {"kind": "delta"}
    if found:
        dto["state"] = "ok"
        dto["value"] = _string(value)
    else:
        dto["state"] = "blank"
        dto["value"] = ""
        dto["reason"] = f"no value for binding {name}"
    dto["label"] = _string(element.get("label"))
    direction_binding = _binding_name(element, "directionBinding")
    direction_value, direction_found = _lookup(bindings, direction_binding)
    dto["direction"] = _direction(direction_value) if direction_found else "flat"
    dto["window"] = _string(element.get("window"))
    return dto


def _render_progress(element, bindings) -> dict:
    """Render progress toward a target.

    Both value and target are emitted as numbers: the target comes from
    targetBinding when declared, else from the literal target attribute. The
    state is "ok" only when both exist; one missing side is "blank", and the
    reason names which side is missing.
    """
    name = _binding_name(element)
    raw_value, value_found = _lookup(bindings, name)
    value = _number(raw_value) if value_found else None
    if value is None:
        value_found = False

    if "targetBinding" in element:
        target_name = _binding_name(element, "targetBinding")
        raw_target, target_found = _lookup(bindings, target_name)
        target = _number(raw_target) if target_found else None
        if target is None:
            target_found = False
    else:
        target_name = ""
        target = _number(element.get("target"))
        target_found = target is not None

    dto = {"kind": "progress"}
    if not value_found:
        dto["state"] = "blank"
        dto["value"] = None
        dto["target"] = target if target_found else None
        dto["reason"] = f"no value for binding {name}"
    elif not target_found:
        dto["state"] = "blank"
        dto["value"] = value
        dto["target"] = None
        dto["reason"] = (
            f"no value for binding {target_name}"
            if "targetBinding" in element
            else "no target for progress element"
        )
    else:
        dto["state"] = "ok"
        dto["value"] = value
        dto["target"] = target
    dto["label"] = _string(element.get("label"))
    dto["unit"] = _string(element.get("unit"))
    tone_binding = _binding_name(element, "toneBinding")
    tone_value, tone_found = _lookup(bindings, tone_binding)
    dto["tone"] = _tone(tone_value) if tone_found else _tone(element.get("tone", "ok"))
    return dto


def _render_list(element, bindings) -> dict:
    """Render rows of primary/secondary/meta items.

    A row may be a dict or a bare string, which becomes the primary column. Any
    other row type blanks the whole element, because dropping just that row would
    silently misrepresent the data.
    """
    name = _binding_name(element, "rowsBinding")
    rows, found = _lookup(bindings, name)
    dto = {"kind": "list"}
    _with_optional(dto, element, "title")
    if not found:
        dto["state"] = "blank"
        dto["rows"] = []
        dto["reason"] = f"no value for binding {name}"
        return dto
    if not isinstance(rows, list):
        dto["state"] = "blank"
        dto["rows"] = []
        dto["reason"] = f"rowsBinding {name} must be a list"
        return dto

    rendered_rows = []
    for row in rows:
        if isinstance(row, dict):
            rendered_rows.append(
                {
                    "primary": _string(row.get("primary")),
                    "secondary": _string(row.get("secondary")),
                    "meta": _string(row.get("meta")),
                }
            )
        elif isinstance(row, str):
            rendered_rows.append({"primary": row, "secondary": "", "meta": ""})
        else:
            dto["state"] = "blank"
            dto["rows"] = []
            dto["reason"] = f"rowsBinding {name} has a malformed row"
            return dto
    dto["state"] = "ok"
    dto["rows"] = rendered_rows
    return dto


def _render_table(element, bindings) -> dict:
    """Render a column heading list and its cell rows.

    Columns are echoed as text. Rows may be dicts, read as primary/secondary/
    meta columns, or sequences, kept cell for cell; a malformed row blanks the
    whole table.
    """
    columns = element.get("columns")
    name = _binding_name(element, "rowsBinding")
    rows, found = _lookup(bindings, name)
    dto = {"kind": "table"}
    _with_optional(dto, element, "title")
    if not isinstance(columns, list):
        dto["state"] = "blank"
        dto["columns"] = []
        dto["rows"] = []
        dto["reason"] = "table columns must be a list"
        return dto
    dto["columns"] = [_string(column) for column in columns]
    if not found:
        dto["state"] = "blank"
        dto["rows"] = []
        dto["reason"] = f"no value for binding {name}"
        return dto
    if not isinstance(rows, list):
        dto["state"] = "blank"
        dto["rows"] = []
        dto["reason"] = f"rowsBinding {name} must be a list"
        return dto

    rendered_rows = []
    for row in rows:
        # A table may bind the same structured row dicts a list uses
        # (primary/secondary/meta); plain arrays stay accepted so
        # existing plugins keep their exact cells.
        if isinstance(row, dict):
            rendered_rows.append([
                _string(row.get("primary")),
                _string(row.get("secondary")),
                _string(row.get("meta")),
            ])
            continue
        if not isinstance(row, (list, tuple)):
            dto["state"] = "blank"
            dto["rows"] = []
            dto["reason"] = f"rowsBinding {name} has a malformed row"
            return dto
        rendered_rows.append([_string(cell) for cell in row])
    dto["state"] = "ok"
    dto["rows"] = rendered_rows
    return dto


def _render_sparkline(element, bindings) -> dict:
    """Render a nonempty numeric series with its minimum and maximum.

    The bounds are computed over the points themselves. One non-numeric point
    blanks the element rather than shortening the series, since a partial series
    would show a shape the data does not have.
    """
    name = _binding_name(element, "pointsBinding")
    points, found = _lookup(bindings, name)
    dto = {"kind": "sparkline"}
    _with_optional(dto, element, "label")
    if not found:
        dto["state"] = "blank"
        dto["points"] = []
        dto["min"] = None
        dto["max"] = None
        dto["reason"] = f"no value for binding {name}"
        return dto
    if not isinstance(points, list) or not points:
        dto["state"] = "blank"
        dto["points"] = []
        dto["min"] = None
        dto["max"] = None
        dto["reason"] = f"pointsBinding {name} must be a nonempty list"
        return dto

    numbers = []
    for point in points:
        number = _number(point)
        if number is None:
            dto["state"] = "blank"
            dto["points"] = []
            dto["min"] = None
            dto["max"] = None
            dto["reason"] = f"pointsBinding {name} contains a non-numeric point"
            return dto
        numbers.append(number)
    dto["state"] = "ok"
    dto["points"] = numbers
    dto["min"] = min(numbers)
    dto["max"] = max(numbers)
    return dto


def _render_status(element, bindings) -> dict:
    """Render a status line with its tone.

    The tone comes from toneBinding when that resolves, and otherwise from the
    literal tone attribute, defaulting to "ok".
    """
    name = _binding_name(element)
    value, found = _lookup(bindings, name)
    dto = {"kind": "status"}
    if found:
        dto["state"] = "ok"
        dto["text"] = _string(value)
    else:
        dto["state"] = "blank"
        dto["text"] = ""
        dto["reason"] = f"no value for binding {name}"

    tone_binding = _binding_name(element, "toneBinding")
    tone_value, tone_found = _lookup(bindings, tone_binding)
    dto["tone"] = _tone(tone_value) if tone_found else _tone(element.get("tone", "ok"))
    return dto


def _render_timeline(element, bindings) -> dict:
    """Render time/title/meta timeline items in binding order.

    The order is the data's own order and is not sorted here; an item that is not
    an object blanks the whole element.
    """
    name = _binding_name(element, "itemsBinding")
    items, found = _lookup(bindings, name)
    dto = {"kind": "timeline"}
    _with_optional(dto, element, "title")
    if not found:
        dto["state"] = "blank"
        dto["items"] = []
        dto["reason"] = f"no value for binding {name}"
        return dto
    if not isinstance(items, list):
        dto["state"] = "blank"
        dto["items"] = []
        dto["reason"] = f"itemsBinding {name} must be a list"
        return dto

    rendered_items = []
    for item in items:
        if not isinstance(item, dict):
            dto["state"] = "blank"
            dto["items"] = []
            dto["reason"] = f"itemsBinding {name} has a malformed item"
            return dto
        rendered_items.append(
            {
                "time": _string(item.get("time")),
                "title": _string(item.get("title")),
                "meta": _string(item.get("meta")),
            }
        )
    dto["state"] = "ok"
    dto["items"] = rendered_items
    return dto


def _render_checklist(element, bindings) -> dict:
    """Render text/done/due checklist items.

    done goes through the boolean coercion, so "yes", "done" and 1 all render as
    ticked; due is free text and is not parsed as a date.
    """
    name = _binding_name(element, "itemsBinding")
    items, found = _lookup(bindings, name)
    dto = {"kind": "checklist"}
    _with_optional(dto, element, "title")
    if not found:
        dto["state"] = "blank"
        dto["items"] = []
        dto["reason"] = f"no value for binding {name}"
        return dto
    if not isinstance(items, list):
        dto["state"] = "blank"
        dto["items"] = []
        dto["reason"] = f"itemsBinding {name} must be a list"
        return dto

    rendered_items = []
    for item in items:
        if not isinstance(item, dict):
            dto["state"] = "blank"
            dto["items"] = []
            dto["reason"] = f"itemsBinding {name} has a malformed item"
            return dto
        rendered_items.append(
            {
                "text": _string(item.get("text")),
                "done": _boolean(item.get("done")),
                "due": _string(item.get("due")),
            }
        )
    dto["state"] = "ok"
    dto["items"] = rendered_items
    return dto


_RENDERERS = {
    "metric": _render_metric,
    "text": _render_text,
    "delta": _render_delta,
    "progress": _render_progress,
    "list": _render_list,
    "table": _render_table,
    "sparkline": _render_sparkline,
    "status": _render_status,
    "timeline": _render_timeline,
    "checklist": _render_checklist,
}


def _blank(kind: str, element: dict, reason: str) -> dict:
    """Minimal blank DTO for a kind whose structured data went bad."""
    dto = {"kind": kind, "state": "blank", "reason": reason}
    if kind == "metric":
        dto["label"] = _string(element.get("label"))
        dto["value"] = ""
    elif kind == "text":
        dto["text"] = ""
    elif kind == "delta":
        dto["label"] = _string(element.get("label"))
        dto["value"] = ""
        dto["direction"] = "flat"
        dto["window"] = _string(element.get("window"))
    elif kind == "progress":
        dto["label"] = _string(element.get("label"))
        dto["value"] = None
        dto["target"] = None
        dto["unit"] = _string(element.get("unit"))
        dto["tone"] = "ok"
    elif kind == "list":
        dto["rows"] = []
        _with_optional(dto, element, "title")
    elif kind == "table":
        dto["rows"] = []
        columns = element.get("columns")
        dto["columns"] = (
            [_string(column) for column in columns]
            if isinstance(columns, list)
            else []
        )
        _with_optional(dto, element, "title")
    elif kind == "sparkline":
        dto["points"] = []
        dto["min"] = None
        dto["max"] = None
        _with_optional(dto, element, "label")
    elif kind == "status":
        dto["text"] = ""
        dto["tone"] = "ok"
    elif kind == "timeline":
        dto["items"] = []
        _with_optional(dto, element, "title")
    elif kind == "checklist":
        dto["items"] = []
        _with_optional(dto, element, "title")
    return dto


# ---------------------------------------------------------------------------
# Sample rendering
# ---------------------------------------------------------------------------


def render_sample(plugin_dir) -> dict:
    """Render a v2 plugin's sample fixture without reading outside plugin_dir."""
    base = Path(plugin_dir).resolve()
    manifest = _load_json_object(base / "manifest.json", "manifest.json")

    sample_name = manifest.get("sample")
    if not isinstance(sample_name, str) or not sample_name:
        raise PluginRenderError("manifest.json has no sample path")
    sample_path = _contained(base, sample_name)
    if not sample_path.is_file():
        raise PluginRenderError(f"sample file not found: {sample_name}")

    sample = _load_json_object(sample_path, f"sample file {sample_name}")
    bindings = sample.get("bindings")
    if not isinstance(bindings, dict):
        raise PluginRenderError(f"sample file {sample_name} has no bindings object")

    ui_schema = _first_ui_schema(base, manifest)
    state = _string(sample.get("state", "ok"))
    return {
        "elements": render_elements(ui_schema, bindings),
        "status": "fresh" if state == "ok" else "attention",
        "cause": "",
        "checked_at": _string(sample.get("checkedAt", "")),
    }


def _contained(base: Path, relative: str) -> Path:
    """Resolve a manifest-relative path, refusing anything outside base."""
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise PluginRenderError(f"path escapes the plugin directory: {relative}")
    resolved = (base / path).resolve()
    if resolved != base and base not in resolved.parents:
        raise PluginRenderError(f"path escapes the plugin directory: {relative}")
    return resolved


def _load_json_object(path: Path, label: str) -> dict:
    """Parse a file as a JSON object, raising PluginRenderError on any failure.

    label names the document in the error message, which is the manifest-relative
    name rather than the resolved path. A UTF-8 BOM is tolerated; a non-object
    document is rejected, not coerced.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PluginRenderError(f"cannot read {label}: {exc}") from exc
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PluginRenderError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise PluginRenderError(f"{label} must be a JSON object")
    return document


def _first_ui_schema(base: Path, manifest: dict) -> dict:
    """Return the first ui-schema document the manifest's widgets contribute.

    Widgets are inspected in manifest order and non ui-schema renders are
    skipped. The document path goes through the containment check, so a manifest
    cannot point the renderer outside its own plugin directory.
    """
    contributes = manifest.get("contributes")
    widgets = contributes.get("widgets") if isinstance(contributes, dict) else None
    if isinstance(widgets, list):
        for widget in widgets:
            if not isinstance(widget, dict):
                continue
            render = widget.get("render")
            if not isinstance(render, dict):
                continue
            if render.get("type") != "ui-schema":
                continue
            render_file = render.get("file")
            if not isinstance(render_file, str):
                continue
            path = _contained(base, render_file)
            return _load_json_object(path, f"ui-schema file {render_file}")
    raise PluginRenderError("manifest.json has no widget ui-schema render")
