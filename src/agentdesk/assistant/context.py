"""Widget context: the derived abstractions the assistant may read.

The manager never re-explains her context: the prompt carries a compact
summary of what the connected widgets know, and nothing more. Derived
only: file names, counts, example rows from the delta, the meeting name.
Raw files never leave the machine.
"""

import json


def _file_name(path: str) -> str:
    """Return the last path segment, accepting either separator.

    Only the file name reaches the prompt, never the user's directory
    layout; an empty path, or one ending in a separator, reads as
    "workbook".
    """
    return str(path).replace("\\", "/").rsplit("/", 1)[-1] or "workbook"


def _excel_lines(excel_status: dict | None) -> list[str]:
    """Describe the watched workbook as prompt lines.

    Empty unless the widget is configured. A delta is summarised by count
    with at most three added and three removed rows; before the first delta
    the stored example rows stand in. Each row is one compact JSON line.
    """
    if not excel_status or not excel_status.get("configured"):
        return []
    lines = [f"Sales workbook watched: {_file_name(excel_status.get('path', ''))}"]
    state = excel_status.get("state")
    lines.append(f"Sales data state: {state}")
    delta = excel_status.get("delta")
    if delta:
        lines.append(
            f"Changed in the last 24 hours: {len(delta.get('added', []))} rows added,"
            f" {len(delta.get('removed', []))} rows removed."
        )
        for row in delta.get("added", [])[:3]:
            lines.append(f"  added row: {json.dumps(row, ensure_ascii=False)}")
        for row in delta.get("removed", [])[:3]:
            lines.append(f"  removed row: {json.dumps(row, ensure_ascii=False)}")
    else:
        # No delta yet (first snapshot): the current shape still helps.
        for row in excel_status.get("examples", []):
            lines.append(f"  row: {json.dumps(row, ensure_ascii=False)}")
    return lines


def _calendar_lines(calendar_status: dict | None) -> list[str]:
    """Describe the calendar widget as prompt lines.

    Empty unless configured. With a key event the line names it and its
    start; without one only the widget state, so the prompt still says the
    calendar was read.
    """
    if not calendar_status or not calendar_status.get("configured"):
        return []
    event = calendar_status.get("keyEvent")
    if not event:
        return [f"Calendar: {calendar_status.get('state')}"]
    return [
        "Today's key commitment: {subject} at {start}.".format(
            subject=event["subject"], start=event["start"]
        )
    ]


def build_context(
    excel_status: dict | None,
    calendar_status: dict | None,
    facts_block: str = "",
) -> str:
    """The context block prepended to assistant and research prompts.

    `facts_block` (the memory recall, already bounded by memory/service)
    rides first when the assistant turn recalls anything: derived
    abstractions the prompt may read, never instructions or content the
    user did not review on the memory page.
    """
    lines = []
    if facts_block:
        lines.append(facts_block)
    lines.append("Connected widget context (derived, read-only):")
    lines += _excel_lines(excel_status)
    lines += _calendar_lines(calendar_status)
    if lines[-1] == "Connected widget context (derived, read-only):":
        lines.append("(no sources connected yet)")
    return "\n".join(lines)
