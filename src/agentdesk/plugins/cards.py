"""The widget card: one constructor and one serializer.

Every card the desk serves is assembled here, in the four shapes the
runtime emits (setup, tracker, attention, widget), with the plugin
identity mandatory at construction: a card that cannot receive its
reading is unrepresentable, so the missing-pluginId bug (#165) cannot
recur. The serializer is the one place a card becomes the dashboard
API's camelCase shape.
"""
from __future__ import annotations

from agentdesk.plugins.render import render_elements
from agentdesk.plugins.vocabulary import DELTA, METRIC, SPARKLINE, TEXT


class CardError(Exception):
    """A card-construction refusal: ``code`` is the stable vocabulary."""

    def __init__(self, code: str, message: str) -> None:
        """Carry the stable refusal code beside the human message.

        The code is the token callers branch on and is not derived from the
        message; ``str(exc)`` returns the message, the sentence a person reads.
        """
        super().__init__(message)
        self.code = code
        self.message = message


def _format_number(value) -> str:
    """Format a number for a card label.

    Whole values print without a decimal point, everything else with two
    decimals. The value is converted through float, so a non-numeric argument
    raises instead of rendering an empty label.
    """
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}"


def _card(plugin_id: str, instance_id: str, *, card_id: str, title: str,
          version: str, pilot: bool, freshness: str, state: str = "enabled",
          cause: str = "", checked_at: str = "", payload=None,
          manifest: dict | None = None) -> dict:
    """Assemble the one card dict every shape is built from.

    The field list lives here and nowhere else: the four shape
    constructors below decide the values, this decides the wire form.
    A missing plugin identity is refused by name (``card:missing-identity``)
    before anything is built, which is the enforcement #165 never had.
    """
    if not plugin_id or not instance_id:
        raise CardError(
            "card:missing-identity",
            "A card needs both a plugin id and an instance id, or no "
            "reading can reach it.",
        )
    card = {
        "id": card_id,
        "title": title,
        "version": version,
        "pilot": bool(pilot),
        "state": state,
        "freshness": freshness,
        "cause": cause,
        "checked_at": checked_at,
        "pluginId": plugin_id,
        "instanceId": instance_id,
    }
    if manifest is not None:
        card["manifest"] = manifest
    card["payload"] = payload
    return card


def setup_card(plugin_id: str, instance_id: str, *, title: str, version: str,
               pilot: bool, step: str) -> dict:
    """Build the card for an instance that is not yet showing live values.

    The step is the wizard step the card should resume at. The card is keyed by
    the bare plugin id only for an unconfirmed main instance, matching the layout
    key, and by "<plugin>~<instance>" everywhere else. The pilot badge tells the
    truth about the install (T6): a wizard plugin runs in pilot mode, and its
    cards say so instead of hiding the badge while the views are spent.
    """
    card_id = (plugin_id if instance_id == "main" and step != "done"
               else f"{plugin_id}~{instance_id}")
    return _card(plugin_id, instance_id, card_id=card_id, title=title,
                 version=version, pilot=pilot, freshness="setup",
                 payload={
                     "elements": [],
                     "setup": {
                         "pluginId": plugin_id,
                         "instanceId": instance_id,
                         "name": title,
                         "step": step,
                     },
                 })


def tracker_card(plugin_id: str, instance_id: str, *, title: str,
                 version: str, pilot: bool, reading: dict,
                 manifest: dict | None = None) -> dict:
    """Build a confirmed instance's live card from its tracker reading.

    The card is always keyed "<plugin>~<instance>" (a confirmed main keeps
    that key too, the historical tracker's confirmed card id) and its payload
    carries the elements, the fresh status and the full tracker record. The
    base card is assembled first, so the identity refusal answers before the
    reading is even reduced.

    When the plugin's ui-schema asks for a face other than the classic one
    (the manager chose a big number, a bar, a table or a trend when they built
    it), the face is rendered from that schema and the reading's own bindings.
    The classic face stays the default, so every plugin built before the
    wizard asked the question renders exactly as it always did.
    """
    card = _card(plugin_id, instance_id,
                 card_id=f"{plugin_id}~{instance_id}", title=title,
                 version=version, pilot=pilot, freshness="fresh")
    payload = _tracker_payload(title, reading)
    face = _rendered_face(manifest, reading)
    if face is not None:
        payload["elements"] = face
        # The tracker block stays: it is the reading's provenance, and the SPA
        # picks its presentation from `face`, never from the block's presence.
        payload["face"] = "ui-schema"
    card["payload"] = payload
    return card


def _rendered_face(manifest: dict | None, reading: dict) -> list | None:
    """The elements a tracker plugin's own ui-schema asks for, or None.

    None means "draw the classic tracker face", which is what every plugin
    built before the wizard asked the question must keep: their ui-schema is
    the classic card's own schema, and excel-report's even carries a fourth
    text element, so guessing from element shapes would quietly take the
    chart away from the flagship tracker. The marker is positive instead: the
    runtime sets ``_chosen_face`` only for a wizard-built plugin, whose tile
    was composed from the manager's own choice.
    """
    if not isinstance(manifest, dict):
        return None
    elements = manifest.get("_ui_elements")
    if not isinstance(elements, list) or not elements:
        return None
    if not manifest.get("_chosen_face"):
        return None
    bindings = _tracker_bindings(reading)
    rendered = render_elements({"elements": elements}, bindings)
    return rendered or None


def _tracker_bindings(reading: dict) -> dict:
    """The reading's values under the names a ui-schema element binds to."""
    points = reading.get("points") or []
    table = reading.get("table") or {}
    rows = table.get("rows") or []
    return {
        "value": _format_number(reading["value"]),
        "delta": reading["delta"],
        "direction": reading["direction"],
        "points": points,
        "rows": rows,
        "table": rows,
        "file": reading["file"],
        "target": (reading.get("goal") or {}).get("value"),
    }


def _tracker_payload(title: str, reading: dict) -> dict:
    """Reduce one tracker reading into the payload a live card serves.

    The elements are the card face (value, change, workbook, optional pace
    and history); the tracker block repeats the reading with its provenance,
    so a client can draw the card without re-reading the file.
    """
    elements = [
        {"kind": METRIC, "label": "Value",
         "value": _format_number(reading["value"])},
        {"kind": DELTA, "label": "Change", "value": reading["delta"],
         "direction": reading["direction"]},
        {"kind": TEXT, "label": "Workbook", "text": reading["file"]},
    ]
    if reading.get("paceNote"):
        elements.append({"kind": TEXT, "label": "Pace",
                         "text": reading["paceNote"]})
    points = reading.get("points") or []
    chart = reading.get("chart") or "line"
    if chart == "line" and len(points) >= 2:
        elements.append({"kind": SPARKLINE, "label": "History",
                         "points": points})
    goal = reading.get("goal") if isinstance(reading.get("goal"), dict) else None
    return {
        "elements": elements,
        "status": "fresh",
        "tracker": {
            "name": title,
            "value": _format_number(reading["value"]),
            "unit": reading.get("unit") or "",
            "delta": reading["delta"],
            "direction": reading["direction"],
            "points": points,
            "chart": reading.get("chart") or "line",
            "axis": reading.get("axis") or "reading",
            "labels": reading.get("labels") or [],
            "deltaLabel": reading.get("deltaLabel") or "",
            "seriesNote": reading.get("seriesNote") or "",
            "file": reading["file"],
            "rowsSeen": reading.get("rowsSeen", 0),
            "labelColumn": reading.get("labelColumn") or "",
            "valueColumn": reading.get("valueColumn") or "",
            "table": reading.get("table") or {"headers": [], "rows": []},
            "readAt": reading.get("readAt", 0),
            "sample": bool(reading.get("sample")),
            "paceNote": reading.get("paceNote") or "",
            "goal": None if not goal else {
                "value": _format_number(goal.get("value")),
                "unit": goal.get("unit") or "",
            },
        },
    }


def attention_card(plugin_id: str, instance_id: str, *, card_id: str,
                   title: str, version: str, pilot: bool, cause: str,
                   state: str = "enabled",
                   manifest: dict | None = None) -> dict:
    """Build the card for a source that cannot be read: the reason, no value.

    A reading that cannot be produced becomes an attention card carrying the
    cause instead of a stale value, whichever family the plugin belongs to;
    the caller names the card id because the keying rule belongs to the shape
    the card replaces (a plugin's own key, or its instance's).
    """
    return _card(plugin_id, instance_id, card_id=card_id, title=title,
                 version=version, pilot=pilot, state=state,
                 freshness="attention", cause=cause, payload=None,
                 manifest=manifest)


def widget_card(plugin_id: str, instance_id: str, *, title: str, version: str,
                pilot: bool, state: str, data: dict, payload,
                manifest: dict) -> dict:
    """Build a single-instance plugin's card from one runner read.

    ``data`` is the probe-shaped status (fresh or attention with a cause,
    and when it was checked); ``payload`` is the bound ui-schema render
    model or None when nothing bound. The source's stable reason code rides
    along as sourceReason, so a surface can decide on the code (no-transport)
    rather than decoding the reader sentence; card_to_api does not serve it.
    """
    card = _card(plugin_id, instance_id, card_id=plugin_id, title=title,
                 version=version, pilot=pilot, state=state,
                 freshness=data.get("status", "attention"),
                 cause=data.get("cause", ""),
                 checked_at=data.get("checked_at", ""),
                 payload=payload, manifest=manifest)
    card["sourceReason"] = str(data.get("reason") or "")
    # A hand-kept number can only be supplied by the manager, so its tile
    # carries the form that supplies it.
    source = (((manifest or {}).get("contributes") or {}).get("widgets") or [{}])[0]
    if isinstance(source, dict) and (source.get("dataSource") or {}).get("type") == "manual-metric":
        card["manualMetric"] = plugin_id
    return card


def card_to_api(card: dict, title: str | None = None) -> dict:
    """Serialize one card into the dashboard API's camelCase shape.

    This is the only place the card's snake_case fields become the payload's
    camelCase ones, in this order, so the API JSON stays byte-for-byte what
    it has been. The manifest never travels to the API. ``title`` overrides
    the card's own when the layout renamed it. The three fields a
    pre-factory card could lack keep the empty defaults the payload always
    served.
    """
    manual_metric = card.get("manualMetric")
    out = {
        "id": card["id"],
        "title": card["title"] if title is None else title,
        "version": card["version"],
        "pilot": card["pilot"],
        "state": card["state"],
        "freshness": card["freshness"],
        "cause": card["cause"],
        "checkedAt": card.get("checked_at", ""),
        "pluginId": card.get("pluginId", ""),
        "instanceId": card.get("instanceId", ""),
        "payload": card.get("payload"),
    }
    # Only a hand-kept number carries this, so the shape every other card
    # serves stays exactly what it has always been.
    if manual_metric:
        out["manualMetric"] = manual_metric
    return out
